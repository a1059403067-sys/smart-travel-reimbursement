// 对话历史持久化 E2E（REQ-11，真实后端）：
// 登录 → 连发 4 条消息 → 刷新页面：首屏仅最近 3 条 → 向上滚动翻页加载全部
// → 退出重登：历史仍在
// 用法：node verify-history.mjs（需后端 8006 与 dev 前端 3002 在跑）
import { chromium } from 'playwright-core'

const DEV_URL = 'http://localhost:3002'
const results = []
const check = (name, ok, extra = '') => {
  results.push({ name, ok, extra })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? ' — ' + extra : ''}`)
}

async function login(page) {
  await page.goto(`${DEV_URL}/login`, { waitUntil: 'networkidle' })
  await page.fill('input[placeholder="请输入用户名"]', 'admin')
  await page.fill('input[placeholder="请输入密码"]', 'Admin@123456')
  await page.click('button:has-text("登录")')
  await page.waitForURL('**/dashboard', { timeout: 15000 })
}

async function sendMessage(page, text) {
  await page.fill('textarea', text)
  await page.click('.input-actions button')
  // 等流式结束：发送按钮恢复可用
  await page.waitForFunction(
    () => {
      const btn = document.querySelector('.input-actions button')
      return btn && !btn.disabled && btn.getAttribute('aria-disabled') !== 'true'
    },
    { timeout: 90000 }
  )
  await page.waitForTimeout(800)
}

async function bubbleCount(page) {
  return await page.$$eval('.chat-bubble', els => els.length).catch(() => 0)
}

try {
  const browser = await chromium.launch({ channel: 'msedge', headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  page.setDefaultTimeout(30000)

  // 1. 登录并连发 4 条消息（每用户固定会话，落库由后端 REQ-11 负责）
  await login(page)
  await page.goto(`${DEV_URL}/chat`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1000)
  const initialCount = await bubbleCount(page)
  check('对话页打开（初始历史渲染）', initialCount >= 0, `初始气泡=${initialCount}`)

  for (let i = 1; i <= 4; i++) {
    await sendMessage(page, `你好，这是历史测试第 ${i} 条`)
    const n = await bubbleCount(page)
    console.log(`  [发送 ${i}/4] 当前气泡=${n}`)
  }
  const afterSend = await bubbleCount(page)

  // 2. 刷新页面：历史从后端重新加载（首屏请求 limit=3；内容不满一屏时自动补载）
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(2500)
  const afterReload = await bubbleCount(page)
  check('刷新后历史仍在（>=3 条）', afterReload >= 3, `气泡=${afterReload}（发送后总数=${afterSend}）`)

  // 3. 向上滚动到顶触发翻页，直到显示"已显示全部历史消息"
  let scrolled = 0
  for (let i = 0; i < 8; i++) {
    const noMore = await page.$('.muted-tip')
    if (noMore) break
    await page.$eval('.chat-scroll', el => { el.scrollTop = 0 })
    await page.waitForTimeout(1500)
    scrolled++
  }
  const finalCount = await bubbleCount(page)
  const noMoreTip = await page.$('.muted-tip')
  check('向上滚动翻页加载全部历史', finalCount >= afterSend, `气泡=${finalCount}（发送后=${afterSend}），翻页次数=${scrolled}`)
  check('显示「已显示全部历史消息」', !!noMoreTip)

  // 4. 退出重登：历史仍在（新 context = 全新浏览器会话）
  const page2 = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  await login(page2)
  await page2.goto(`${DEV_URL}/chat`, { waitUntil: 'networkidle' })
  await page2.waitForTimeout(2000)
  const reloginCount = await page2.$$eval('.chat-bubble', els => els.length)
  check('退出重登后历史仍在', reloginCount >= 3, `气泡=${reloginCount}`)

  await page.screenshot({ path: 'screenshots/chat-history.png', fullPage: true })
  console.log('SCREENSHOT: screenshots/chat-history.png')
  await browser.close()

  const failed = results.filter(r => !r.ok)
  console.log(failed.length === 0 ? 'HISTORY E2E: ALL PASS' : `HISTORY E2E: ${failed.length} FAILED`)
  process.exit(failed.length === 0 ? 0 : 1)
} catch (e) {
  console.error('HISTORY E2E: ERROR', e.message)
  process.exit(2)
}
