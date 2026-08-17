"""
Cookie Auto-Login ULTIMATE Pro - HTML Report Generator
Version: 5.0 (version_one)

Generates a standalone HTML report from CookieManager.get_all_data_for_report().
No external deps (pure string templating).
"""


class HTMLReportGenerator:
    @staticmethod
    def generate(data, output_path):
        total = data.get('total', 0)
        success = data.get('success', 0)
        failed = data.get('failed', 0)
        unknown = data.get('unknown', 0)
        domains = data.get('domains', [])

        success_pct = (success / total * 100) if total else 0

        rows = []
        for d in domains:
            status = d.get('status', 'unknown')
            if status == 'success':
                badge = '<span class="badge ok">✓ Success</span>'
            elif status == 'failed':
                badge = '<span class="badge bad">✗ Failed</span>'
            else:
                badge = '<span class="badge unk">? Unknown</span>'

            top = d.get('top_cookies', [])
            top_html = "<br>".join(
                f"{c['name']} = {c['value']}…" for c in top
            ) if top else "—"

            rows.append(f"""
            <tr>
                <td>{d.get('domain','')}</td>
                <td>{badge}</td>
                <td>{d.get('score',0)}</td>
                <td>{d.get('cookie_count',0)}</td>
                <td>{d.get('category','Other')}</td>
                <td class="cookies">{top_html}</td>
            </tr>
            """)

        rows_html = "\n".join(rows)

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cookie Auto-Login Report</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 0; background: #f7fafc; color: #2d3748; }}
  header {{ background: #1a202c; color: white; padding: 24px 32px; }}
  header h1 {{ margin: 0; font-size: 22px; }}
  header p {{ margin: 6px 0 0; color: #cbd5e0; font-size: 12px; }}
  .summary {{ display: flex; gap: 16px; padding: 24px 32px; flex-wrap: wrap; }}
  .card {{ background: white; border: 1px solid #e2e8f0; border-radius: 10px; padding: 16px 20px; min-width: 120px; box-shadow: 0 1px 3px rgba(0,0,0,.06); }}
  .card .num {{ font-size: 28px; font-weight: 700; }}
  .card .lbl {{ font-size: 12px; color: #718096; text-transform: uppercase; letter-spacing: .04em; }}
  .card.ok .num {{ color: #10B981; }}
  .card.bad .num {{ color: #EF4444; }}
  .card.unk .num {{ color: #FBBF24; }}
  table {{ width: calc(100% - 64px); margin: 0 32px 32px; border-collapse: collapse; background: white; border-radius: 10px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.06); }}
  th, td {{ text-align: left; padding: 10px 14px; border-bottom: 1px solid #edf2f7; font-size: 13px; vertical-align: top; }}
  th {{ background: #edf2f7; color: #4a5568; text-transform: uppercase; font-size: 11px; letter-spacing: .04em; }}
  .badge {{ padding: 3px 8px; border-radius: 6px; font-size: 12px; font-weight: 600; }}
  .badge.ok {{ background: #d1fae5; color: #065f46; }}
  .badge.bad {{ background: #fee2e2; color: #991b1b; }}
  .badge.unk {{ background: #fef3c7; color: #92400e; }}
  td.cookies {{ font-family: monospace; font-size: 11px; color: #4a5568; }}
</style>
</head>
<body>
<header>
  <h1>🔐 Cookie Auto-Login Report</h1>
  <p>Generated {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ·
     Success rate: {success_pct:.1f}%</p>
</header>
<div class="summary">
  <div class="card"><div class="num">{total}</div><div class="lbl">Total</div></div>
  <div class="card ok"><div class="num">{success}</div><div class="lbl">Working</div></div>
  <div class="card bad"><div class="num">{failed}</div><div class="lbl">Failed</div></div>
  <div class="card unk"><div class="num">{unknown}</div><div class="lbl">Unknown</div></div>
</div>
<table>
  <thead>
    <tr><th>Domain</th><th>Status</th><th>Score</th><th>Cookies</th><th>Category</th><th>Top Cookies</th></tr>
  </thead>
  <tbody>
  {rows_html}
  </tbody>
</table>
</body>
</html>
"""
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)
        return output_path
