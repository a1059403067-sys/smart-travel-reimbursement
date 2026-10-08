// R-01 实机验证：图表容器在 v-if 内是否正常渲染（canvas 数量/尺寸断言 + 截图）
// 用法：node verify-r01.mjs（需 vite dev 已跑在 3001；使用系统 Edge headless）
import { chromium } from 'playwright-core'

const VITE_URL = 'http://localhost:3001'

const dashboardMock = {
  summary: { total_trips: 10, total_amount: 40200.0, pending_approvals: 2, month_new_trips: 10 },
  department_expense: [
    { name: '研发部', value: 18450.0, percentage: 45.9 },
    { name: '市场部', value: 11500.0, percentage: 37.8 },
  ],
  monthly_trend: [
    { month: '2026-05', trips: 2, amount: 5000.0 },
    { month: '2026-08', trips: 4, amount: 12000.0 },
    { month: '2026-10', trips: 7, amount: 29200.0 },
  ],
  expense_by_type: [
    { name: '项目驻场', value: 12600.0, percentage: 31.3 },
    { name: '客户拜访', value: 9000.0, percentage: 22.4 },
  ],
  reimbursement_status: [
    { name: '草稿', value: 1 },
    { name: '待审批', value: 2 },
    { name: '已通过', value: 3 },
    { name: '已驳回', value: 1 },
    { name: '已打款', value: 2 },
  ],
}

try {
  const browser = await chromium.launch({ channel: 'msedge', headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })

  // mock API（不依赖后端是否启动）
  await page.route('**/api/travel/dashboard', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(dashboardMock) })
  )
  await page.route('**/api/auth/me', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ user_id: '1', role: 'admin', tenant_id: 'tenant_default' }) })
  )

  // 注入登录态，直达 /dashboard
  await page.addInitScript(() => {
    localStorage.setItem('travel-token', 'test-token')
    localStorage.setItem('travel-user', JSON.stringify({ user_id: '1', username: 'admin', real_name: '系统管理员', role: 'admin' }))
  })

  await page.goto(`${VITE_URL}/dashboard`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1500) // 等图表渲染动画完成

  const canvases = await page.evaluate(() =>
    Array.from(document.querySelectorAll('canvas')).map(c => ({
      width: c.width,
      height: c.height,
      clientWidth: c.clientWidth,
      clientHeight: c.clientHeight,
    }))
  )

  console.log('CANVAS_COUNT:', canvases.length)
  canvases.forEach((c, i) => console.log(`canvas[${i}]:`, JSON.stringify(c)))

  const statValues = await page.$$eval('.stat-value', els => els.map(e => e.textContent?.trim()))
  console.log('STAT_CARDS:', JSON.stringify(statValues))

  await page.screenshot({ path: 'screenshots/dashboard.png', fullPage: true })
  console.log('SCREENSHOT: screenshots/dashboard.png')

  // 断言：4 个图表 canvas 均真实渲染（有像素尺寸且占据布局空间）
  const ok =
    canvases.length === 4 &&
    canvases.every(c => c.width > 0 && c.height > 0 && c.clientWidth > 0 && c.clientHeight > 0) &&
    statValues.length === 4
  console.log(ok ? 'VERIFY: PASS' : 'VERIFY: FAIL')
  await browser.close()
  process.exit(ok ? 0 : 1)
} catch (e) {
  console.error('VERIFY: ERROR', e.message)
  process.exit(2)
}
