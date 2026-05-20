import { expect, test, type Page } from '@playwright/test';

const UI_PATH = process.env.UI_PATH || '/static/index.html';

function mockApi(page: Page) {
  page.route('**/api/v1/documents/upload', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ document_id: 'doc-smoke-001' }),
    });
  });

  page.route('**/api/v1/documents/doc-smoke-001/ingest', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ pages_extracted: 12, chunks_created: 48 }),
    });
  });

  page.route('**/api/v1/documents/doc-smoke-001/summary', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        stock_id: '2330',
        period: '2025Q1',
        confidence_level: 'High',
        evidence_status: 'complete',
        investment_advice_detected: false,
        claims: [
          {
            claim:
              '營收維持成長，長段文字驗證自動換行能力：'.repeat(10),
            claim_level: 'observed_fact',
            claim_type: 'financial',
            confidence: 'high',
            source_type: 'financial_evidence',
            section_key: 'key_financials',
            requires_human_review: false,
            recurring: true,
            evidence: [{ page: 12, quoted_text: '營收年增 12.3%' }],
          },
          {
            claim: '管理層預期下半年需求改善，需持續追蹤。',
            claim_level: 'interpretation',
            claim_type: 'narrative',
            confidence: 'medium',
            source_type: 'management_expectation',
            section_key: 'pipeline',
            requires_human_review: true,
            recurring: false,
            rhetorical_risk_flag: true,
            rhetorical_risk_terms: ['顯著'],
            evidence: [{ page: 21, quoted_text: '管理層表示需求有望回升' }],
          },
        ],
        key_findings: [],
        dashboard: {
          kpis: [],
          causal_chain: [],
          non_recurring_adjustments: [],
          risk_surface: [],
          transparency: { evidence_coverage_pct: 100, human_review_count: 1 },
        },
        completeness_warnings: [],
      }),
    });
  });
}

test('dropzone file select shows green confirmation', async ({ page }) => {
  await page.goto(UI_PATH);

  await page.setInputFiles('#pdf_file', {
    name: 'sample.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n'),
  });

  await expect(page.locator('#dropzone')).toHaveClass(/dz-has-file/);
  await expect(page.locator('#dz-filename')).toContainText('sample.pdf');
});

test('stepper advances and results badges render', async ({ page }) => {
  mockApi(page);
  await page.goto(UI_PATH);

  await page.fill('#stock_id', '2330');
  await page.fill('#company_name', '台積電');
  await page.fill('#period', '2025Q1');
  await page.setInputFiles('#pdf_file', {
    name: 'sample.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4\n'),
  });

  await page.click('#upload-btn');
  await expect(page.locator('#sn2')).toHaveClass(/active/);
  await expect(page.locator('#sn1')).toHaveClass(/done/);

  await page.click('#ingest-btn');
  await expect(page.locator('#sn3')).toHaveClass(/active/);
  await expect(page.locator('#sn2')).toHaveClass(/done/);

  await page.click('#summary-btn');
  await expect(page.locator('#results-area')).not.toHaveClass(/hidden/);
  await expect(page.locator('#sn4')).toHaveClass(/active/);
  await expect(page.getByTestId('gov-bar')).toContainText('佐證完整');
  await expect(page.getByTestId('review-count-btn')).toContainText('1 條待確認');
  await expect(page.getByTestId('advice-signal-value')).toContainText('無投資建議');
});

test('error/loading/success states are visible', async ({ page }) => {
  await page.goto(UI_PATH);

  await page.click('#upload-btn');
  await expect(page.locator('#upload-result .alert-error')).toBeVisible();

  await page.route('**/api/v1/documents/upload', async (route) => {
    await new Promise((r) => setTimeout(r, 500));
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ document_id: 'doc-smoke-002' }),
    });
  });

  await page.fill('#stock_id', '2330');
  await page.fill('#company_name', '台積電');
  await page.fill('#period', '2025Q1');
  await page.setInputFiles('#pdf_file', {
    name: 'sample.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4\n'),
  });

  await page.click('#upload-btn');
  await expect(page.locator('#upload-btn .spinner')).toBeVisible();
  await expect(page.locator('#upload-success-msg')).toContainText('上傳成功');
});

test('mobile layout and long text do not overflow', async ({ page }) => {
  mockApi(page);
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto(UI_PATH);

  await page.fill('#stock_id', '2330');
  await page.fill('#company_name', '台積電');
  await page.fill('#period', '2025Q1');
  await page.setInputFiles('#pdf_file', {
    name: 'sample.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4\n'),
  });

  await page.click('#upload-btn');
  await page.click('#ingest-btn');
  await page.click('#summary-btn');

  await expect(page.locator('.results-card')).toBeVisible();

  const hasOverflow = await page.evaluate(() => {
    const root = document.documentElement;
    return root.scrollWidth > root.clientWidth + 1;
  });
  expect(hasOverflow).toBeFalsy();
});
