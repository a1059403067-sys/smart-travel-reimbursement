// 注册流程端到端验证（REQ-9/10，真实后端）：
// 打开注册页 → 填表提交 → 成功弹窗展示 username → 回登录页预填 → 用新账号登录成功
// 用法：node verify-register.mjs（需后端 8006 与 dev 前端 3002 在跑）
import { chromium } from 'playwright-core'

const DEV_URL = 'http://localhost:3002'
const results = []
const check = (name, ok, extra = '') => {
  results.push({ name, ok, extra })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? ' — ' + extra : ''}`)
}

const realName = `测试同事${Math.floor(Math.random() * 9000 + 1000)}`
const password = 'Test@123456'

try {
  const browser = await chromium.launch({ channel: 'msedge', headless: true })
  const page = await browser.newPage()
  page.setDefaultTimeout(30000)

  // 1. 注册页：部门下拉来自 REQ-10 真实接口
  await page.goto(`${DEV_URL}/register`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  const deptOptions = await page.$$eval('.el-select-dropdown__item', els => els.map(e => e.textContent)).catch(() => [])
  await page.click('.el-select')
  await page.waitForTimeout(400)
  const deptVisible = await page.$$eval('.el-select-dropdown__item:visible', els => els.map(e => e.textContent))
  check('部门下拉 5 项（REQ-10 真实数据）', deptVisible.length === 5, deptVisible.join('/'))

  // 2. 填表（先填姓名，再打开部门下拉——fill 会转移焦点导致下拉关闭）
  await page.fill('input[placeholder="请输入真实姓名"]', realName)
  await page.click('.el-select')
  await page.waitForTimeout(600) // 等下拉展开动画稳定
  await page.locator('.el-select-dropdown__item:visible', { hasText: '幕墙设计部' }).first().click({ force: true })
  await page.waitForTimeout(300)
  await page.fill('input[placeholder="至少 6 位"]', password)
  await page.fill('input[placeholder="再次输入密码"]', password)

  // 3. 提交注册
  await page.click('button:has-text("注册")')
  await page.waitForSelector('.el-dialog .el-result', { timeout: 15000 })
  const username = await page.$eval('.success-info b', el => el.textContent?.trim())
  check('注册成功并返回自动生成的 username', !!username, `username=${username}`)

  // 4. 去登录（应预填 username）
  await page.click('.el-dialog button:has-text("去登录")')
  await page.waitForURL(/\/login(\?|$)/, { timeout: 10000 })
  await page.waitForTimeout(500)
  const prefilled = await page.inputValue('input[placeholder="请输入用户名"]')
  check('回跳登录页并预填账号', prefilled === username, `预填=${prefilled}`)

  // 5. 用新账号登录
  await page.fill('input[placeholder="请输入密码"]', password)
  await page.click('button:has-text("登录")')
  await page.waitForURL('**/dashboard', { timeout: 15000 })
  check('新注册账号登录成功', true, `姓名=${realName}`)

  await page.screenshot({ path: 'screenshots/register-success.png', fullPage: true })
  console.log('SCREENSHOT: screenshots/register-success.png')
  await browser.close()

  const failed = results.filter(r => !r.ok)
  console.log(failed.length === 0 ? 'REGISTER E2E: ALL PASS' : `REGISTER E2E: ${failed.length} FAILED`)
  process.exit(failed.length === 0 ? 0 : 1)
} catch (e) {
  console.error('REGISTER E2E: ERROR', e.message)
  process.exit(2)
}
