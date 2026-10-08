// 端到端联调验证（真实后端 8006 + 真实 DB + 真 LLM，无 mock）
// 覆盖：登录 → Dashboard(REQ-1) → 报销单列表(REQ-8) → 审批中心(REQ-6) → 发票页(REQ-7 UI)
//       → 对话页(REQ-5 SSE + guidance 引导卡片，R-24)
// 用法：node verify-e2e.mjs（需后端 8006 与 vite 3001 均在跑）
import { chromium } from 'playwright-core'

const VITE_URL = 'http://localhost:3001'
const results = []
const check = (name, ok, extra = '') => {
  results.push({ name, ok, extra })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? ' — ' + extra : ''}`)
}

try {
  const browser = await chromium.launch({ channel: 'msedge', headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  page.setDefaultTimeout(30000)

  // 1. 登录（真实接口）
  await page.goto(`${VITE_URL}/login`, { waitUntil: 'networkidle' })
  await page.fill('input[placeholder="请输入用户名"]', 'admin')
  await page.fill('input[placeholder="请输入密码"]', 'Admin@123456')
  await page.click('button:has-text("登录")')
  await page.waitForURL('**/dashboard', { timeout: 15000 })
  check('登录成功并跳转 dashboard', true)

  // 2. Dashboard：4 个图表 canvas（费用类型/部门占比/趋势/状态分布）
  await page.waitForTimeout(2500)
  const canvases = await page.evaluate(() =>
    Array.from(document.querySelectorAll('canvas')).map(c => ({ w: c.clientWidth, h: c.clientHeight }))
  )
  check('Dashboard 图表渲染', canvases.length === 4 && canvases.every(c => c.w > 0 && c.h > 0), `${canvases.length} 个 canvas`)
  const statCards = await page.$$eval('.stat-value', els => els.map(e => e.textContent?.trim()).join(','))
  check('Dashboard 统计卡片有数据', statCards.length > 0, statCards)

  // 3. 报销单列表（REQ-8 真实分页）
  await page.goto(`${VITE_URL}/reimbursements`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1200)
  const reimRows = await page.$$eval('.el-table__row', rows => rows.length)
  const reimTotal = await page.$eval('.total-text', el => el.textContent).catch(() => '')
  check('报销单列表渲染', reimRows >= 0 && reimTotal.includes('共'), `行数=${reimRows}, ${reimTotal}`)

  // 4. 审批中心（REQ-6 to_review）
  await page.goto(`${VITE_URL}/approvals`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1200)
  const apprTable = await page.$('.el-table')
  const apprTotal = await page.$eval('.total-text', el => el.textContent).catch(() => '')
  check('审批中心渲染', !!apprTable && apprTotal.includes('共'), apprTotal)

  // 5. 发票页（REQ-7 UI，不实际传文件）
  await page.goto(`${VITE_URL}/invoice`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  const uploadArea = await page.$('.el-upload-dragger')
  check('发票页上传区渲染', !!uploadArea)

  // 6. 对话页（REQ-5 SSE + guidance 卡片 R-24）
  await page.goto(`${VITE_URL}/chat`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  await page.fill('textarea', '发票怎么报销？')
  await page.click('.input-actions button')
  // 等待流式完成（真 LLM，最长 90s）
  await page.waitForFunction(
    () => document.querySelector('.input-actions button')?.getAttribute('disabled') !== null ||
          (document.querySelectorAll('.guidance-card').length > 0),
    { timeout: 2000 }
  ).catch(() => {})
  await page.waitForTimeout(60000)
  const assistantBubbles = await page.$$eval('.chat-bubble.assistant', els => els.length)
  const guidanceCards = await page.$$eval('.guidance-card', els => els.length)
  const routingText = await page.$eval('.routing-tag', el => el.textContent).catch(() => '')
  check('对话页 assistant 回复', assistantBubbles >= 1, `气泡=${assistantBubbles}`)
  check('意图中文展示（R-28）', routingText.includes('发票报销'), routingText)
  check('guidance 引导卡片（R-24）', guidanceCards >= 1, `卡片=${guidanceCards}`)

  await page.screenshot({ path: 'screenshots/chat-guidance.png', fullPage: true })
  console.log('SCREENSHOT: screenshots/chat-guidance.png')

  await browser.close()
  const failed = results.filter(r => !r.ok)
  console.log(failed.length === 0 ? 'E2E: ALL PASS' : `E2E: ${failed.length} FAILED`)
  process.exit(failed.length === 0 ? 0 : 1)
} catch (e) {
  console.error('E2E: ERROR', e.message)
  process.exit(2)
}
