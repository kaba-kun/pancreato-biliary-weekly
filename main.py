import os
import re
import time
import json
import glob
import datetime
import requests
import xml.etree.ElementTree as ET
from google import genai

# ----------------------------------------------------
# 対象ジャーナルの厳格リスト（指定の54誌）
# ----------------------------------------------------
TARGET_JOURNALS = [
    "Nature Reviews Gastroenterology & Hepatology", "Journal of Hepatology",
    "Lancet Gastroenterology & Hepatology", "Gastroenterology", "Gut",
    "Clinical and Molecular Hepatology", "Hepatology", "Clinical Gastroenterology and Hepatology",
    "Gut Microbes", "Endoscopy", "Liver Cancer", "Journal of Crohn's & Colitis", "Journal of Crohns & Colitis",
    "JHEP Reports", "American Journal of Gastroenterology", "Cellular and Molecular Gastroenterology and Hepatology",
    "Hepatobiliary Surgery and Nutrition", "Gastrointestinal Endoscopy", "Hepatology International",
    "World Journal of Gastroenterology", "Alimentary Pharmacology & Therapeutics",
    "United European Gastroenterology Journal", "Annals of Hepatology", "Liver International",
    "Gastric Cancer", "Hepatology Communications", "Journal of Clinical and Translational Hepatology",
    "Esophagus", "Journal of Gastroenterology", "Inflammatory Bowel Diseases",
    "Best Practice & Research Clinical Gastroenterology", "Journal of Gastric Cancer",
    "Gut Pathogens", "Digestive and Liver Disease", "Revista Espanola de Enfermedades Digestivas",
    "Endoscopic Ultrasound", "Helicobacter", "Gut and Liver", "Gastroenterology Report",
    "Seminars in Liver Disease", "Pancreatology", "Hepatobiliary & Pancreatic Diseases International",
    "Liver Transplantation", "Gastroenterology Clinics of North America", "Hepatology Research",
    "Journal of Neurogastroenterology and Motility", "Digestive Endoscopy",
    "Clinical and Translational Gastroenterology", "Journal of Gastroenterology and Hepatology",
    "Digestion", "HPB", "BMC Gastroenterology", "Digestive Diseases and Sciences",
    "Journal of Hepato-Biliary-Pancreatic Sciences", "Pancreas"
]

# ----------------------------------------------------
# 1. PubMedから「臨床研究・原著論文のみ」「指定7日間」を取得
# ----------------------------------------------------
def fetch_pubmed_papers():
    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    
    term_keywords = '("pancreatitis"[Title/Abstract] OR "pancreatic"[Title/Abstract] OR "biliary"[Title/Abstract] OR "ERCP"[Title/Abstract] OR "EUS"[Title/Abstract] OR "cholangiocarcinoma"[Title/Abstract] OR "cholangitis"[Title/Abstract] OR "choledocholithiasis"[Title/Abstract] OR "gallstone"[Title/Abstract] OR "IPMN"[Title/Abstract] OR "PSC"[Title/Abstract] OR "IgG4"[Title/Abstract] OR "neuroendocrine"[Title/Abstract] OR "pancreas transplantation"[Title/Abstract] OR "liver transplantation"[Title/Abstract])'
    type_filter = 'AND ("Clinical Trial"[PT] OR "Observational Study"[PT] OR "Comparative Study"[PT] OR "Multicenter Study"[PT] OR "Validation Study"[PT] OR "Journal Article"[PT]) NOT ("Review"[PT] OR "Editorial"[PT] OR "Letter"[PT] OR "Comment"[PT] OR "Case Reports"[PT])'
    date_filter = 'AND ("last 7 days"[PDat])'
    
    query = f"{term_keywords} {type_filter} {date_filter}"
    
    search_res = requests.get(f"{base_url}/esearch.fcgi", params={
        "db": "pubmed", "term": query, "retmode": "json", "retmax": 60
    }).json()
    
    id_list = search_res.get("esearchresult", {}).get("idlist", [])
    if not id_list:
        return []

    fetch_res = requests.get(f"{base_url}/efetch.fcgi", params={
        "db": "pubmed", "id": ",".join(id_list), "retmode": "xml"
    })
    
    root = ET.fromstring(fetch_res.content)
    papers = []
    
    for article in root.findall(".//PubmedArticle"):
        journal_elem = article.find(".//Journal/Title")
        journal = journal_elem.text if journal_elem is not None else ""
        
        is_target_journal = any(
            target.lower() in journal.lower() or journal.lower() in target.lower() 
            for target in TARGET_JOURNALS
        )
        if not is_target_journal:
            continue

        pmid = article.find(".//PMID").text if article.find(".//PMID") is not None else ""
        title = article.find(".//ArticleTitle").text if article.find(".//ArticleTitle") is not None else ""
        
        author_list = article.findall(".//AuthorList/Author")
        authors_formatted = "Unknown"
        if author_list:
            first_author = author_list[0]
            last_name = first_author.findtext("LastName") or ""
            initials = first_author.findtext("Initials") or ""
            name_str = f"{last_name} {initials}".strip()
            authors_formatted = f"{name_str} et al." if len(author_list) > 1 else name_str

        pub_date_elem = article.find(".//Journal/JournalIssue/PubDate")
        pub_date_str = ""
        if pub_date_elem is not None:
            year = pub_date_elem.findtext("Year") or ""
            month = pub_date_elem.findtext("Month") or ""
            day = pub_date_elem.findtext("Day") or ""
            pub_date_str = f"{year}-{month}-{day}".strip("-") if year else (pub_date_elem.findtext("MedlineDate") or "")

        abstract_texts = article.findall(".//AbstractText")
        abstract = " ".join([elem.text for elem in abstract_texts if elem.text])
        
        lower_abstract = abstract.lower()
        if "mouse model" in lower_abstract or "mice" in lower_abstract or "rat model" in lower_abstract or "in vitro" in lower_abstract:
            continue

        papers.append({
            "pmid": pmid,
            "title": title,
            "journal": journal,
            "author": authors_formatted,
            "pub_date": pub_date_str,
            "abstract": abstract
        })
        
    return papers

# ----------------------------------------------------
# 2. Gemini APIで要約・分類JSONを生成
# ----------------------------------------------------
def analyze_papers_with_gemini(papers):
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

    prompt = f"""
あなたは世界最高峰の胆膵内科ならびに胆膵内視鏡の臨床医かつ臨床研究者です。
以下の{len(papers)}件の論文データから、臨床的インパクトが高い重要な論文を厳選し、指定のJSONフォーマットのみで出力してください。

論文データ:
{papers}

【JSON出力フォーマット (厳守)】
以下のキーを持つJSON配列 (Array) の形式で出力してください：
[
  {{
    "title_ja": "魅力的で正確な日本語タイトル",
    "title_en": "英語原題",
    "journal": "雑誌名",
    "author": "著者名",
    "pub_date": "出版日",
    "category": "カテゴリID (endo, pancreas-benign, biliary-benign, cancer, transplant のいずれか)",
    "is_highlight": trueまたはfalse (最重要3~4報のみtrue),
    "study_design": "研究デザイン・対象症例数 (例: 多施設RCT / 320例)",
    "results": "主要結果 (主要エンドポイントや数値)",
    "takeaway": "臨床的要点 (日常診療への影響)"
  }}
]

【カテゴリID定義】
- endo: 胆膵内視鏡
- pancreas-benign: 膵良性疾患 (急性・慢性・自己免疫性膵炎、IPMN等)
- biliary-benign: 胆道良性疾患 (胆管炎、PSC、総胆管結石、IgG4-SC)
- cancer: 膵・胆道悪性疾患 (膵癌、胆管がん、PNET等)
- transplant: 肝胆膵移植外科

※ 余計な解説テキストやマークダウンは入れず、純粋なJSONテキストのみを出力してください。
"""

    model_name = 'gemini-3.8-flash'
    
    for attempt in range(5):
        try:
            print(f"モデル [{model_name}] で解析を実行中... (試行 {attempt + 1}/5)")
            response = client.models.generate_content(
                model=model_name,
                contents=prompt
            )
            raw_text = response.text.strip()
            if raw_text.startswith("```json"):
                raw_text = raw_text[7:]
            if raw_text.startswith("```"):
                raw_text = raw_text[3:]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3]
            return json.loads(raw_text.strip())
        except Exception as e:
            wait_time = (attempt + 1) * 10
            print(f"一時的な通信エラー ({e})。{wait_time}秒後に再試行します...")
            time.sleep(wait_time)

    raise RuntimeError("AIモデルの呼び出しに失敗しました。")

# ----------------------------------------------------
# 3. 完全固定のApple風HTMLテンプレートをレンダリングする
# ----------------------------------------------------
def build_fixed_html(analyzed_papers, original_papers, date_str, archive_list, is_root=True):
    # ドロップダウンの相対パス生成
    archive_options = []
    if is_root:
        archive_options.append('<option value="index.html" selected>最新号 (最新)</option>')
        for arch in archive_list:
            val = f"archives/{arch['filename']}"
            archive_options.append(f'<option value="{val}">{arch["date"]}</option>')
    else:
        archive_options.append('<option value="../index.html">最新号 (最新)</option>')
        for arch in archive_list:
            if arch["date"] in date_str:
                archive_options.append(f'<option value="{arch["filename"]}" selected>{arch["date"]}</option>')
            else:
                archive_options.append(f'<option value="{arch["filename"]}">{arch["date"]}</option>')

    options_html = "\n".join(archive_options)

    cards_html = ""
    for i, p in enumerate(analyzed_papers):
        # 100%正確なPubMedのPMID（PubMedから得た元の数字）を直接使用
        clean_pmid = original_papers[i]["pmid"] if i < len(original_papers) else ""
        pubmed_url = f"[https://pubmed.ncbi.nlm.nih.gov/](https://pubmed.ncbi.nlm.nih.gov/){clean_pmid}/" if clean_pmid else "#"
        
        highlight_badge = '<span class="badge highlight-badge">⭐ TOP HIGHLIGHT</span>' if p.get("is_highlight") else ''
        category_class = f'{p.get("category", "endo")}'
        if p.get("is_highlight"):
            category_class += " highlight"

        cards_html += f"""
        <a href="{pubmed_url}" target="_blank" rel="noopener noreferrer" class="paper-card-link {category_class}">
            <article class="paper-card">
                <div class="card-header">
                    {highlight_badge}
                    <span class="badge journal-badge">{p.get("journal", "")}</span>
                </div>
                <h2 class="title-ja">{p.get("title_ja", "")}</h2>
                <p class="title-en">{p.get("title_en", "")}</p>
                <div class="meta-row">
                    <span>👤 {p.get("author", "")}</span>
                    <span>📅 {p.get("pub_date", "")}</span>
                    <span class="pmid-badge">PMID: {clean_pmid} ↗</span>
                </div>
                <div class="summary-box">
                    <div class="summary-item"><strong>研究デザイン:</strong> {p.get("study_design", "")}</div>
                    <div class="summary-item"><strong>主要結果:</strong> {p.get("results", "")}</div>
                    <div class="summary-item"><strong>臨床的要点:</strong> {p.get("takeaway", "")}</div>
                </div>
            </article>
        </a>
        """

    full_html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>今週の胆膵疾患研究ハイライト | Pancreatobiliary Weekly Digest</title>
    <meta name="description" content="主要54誌から厳選した胆膵疾患・胆膵内視鏡領域の最新臨床研究（Original Article）ウィークリーダッシュボード。">
    <meta property="og:title" content="今週の胆膵疾患研究ハイライト">
    <meta property="og:description" content="主要54誌から厳選した胆膵領域の最新臨床研究・一文要約サマリー。">
    <meta property="og:type" content="website">
    <link rel="icon" href="data:image/svg+xml,%3Csvg%20xmlns='[http://www.w3.org/2000/svg'%20viewBox='0%200%20100%20100'%3E%3Ctext%20y='.9em'%20font-size='90'%3E%F0%9F%94%AC%3C/text%3E%3C/svg%3E](http://www.w3.org/2000/svg'%20viewBox='0%200%20100%20100'%3E%3Ctext%20y='.9em'%20font-size='90'%3E%F0%9F%94%AC%3C/text%3E%3C/svg%3E)">
    <style>
        :root {{
            --bg-color: #f5f5f7;
            --text-main: #1d1d1f;
            --text-sub: #86868b;
            --card-bg: #ffffff;
            --accent: #0066cc;
            --border-color: rgba(0, 0, 0, 0.08);
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Inter", sans-serif;
            background-color: var(--bg-color);
            color: var(--text-main);
            line-height: 1.5;
            -webkit-font-smoothing: antialiased;
            padding-bottom: 40px;
        }}
        
        header {{
            background: rgba(255, 255, 255, 0.85);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            position: sticky;
            top: 0;
            z-index: 100;
            border-bottom: 1px solid var(--border-color);
            padding: 16px 0 12px;
        }}
        .header-container {{
            max-width: 1000px;
            margin: 0 auto;
            padding: 0 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .site-title {{ font-size: 20px; font-weight: 700; letter-spacing: -0.02em; color: var(--text-main); }}
        .sub-title {{ font-size: 13px; color: var(--text-sub); margin-top: 2px; }}
        .archive-select {{
            padding: 8px 12px;
            border-radius: 8px;
            border: 1px solid var(--border-color);
            background: #fff;
            font-size: 13px;
            cursor: pointer;
            color: var(--text-main);
        }}
        
        nav.tabs-nav {{
            max-width: 1000px;
            margin: 12px auto 0;
            padding: 0 24px;
            display: flex;
            gap: 8px;
            overflow-x: auto;
            white-space: nowrap;
            -ms-overflow-style: none;
            scrollbar-width: none;
        }}
        nav.tabs-nav::-webkit-scrollbar {{
            display: none;
        }}
        .tab-btn {{
            padding: 8px 16px;
            border-radius: 20px;
            border: none;
            background: #e5e5ea;
            color: var(--text-main);
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
            transition: background 0.2s ease, color 0.2s ease;
        }}
        .tab-btn.active {{ background: var(--accent); color: #fff; }}
        
        main {{ max-width: 1000px; margin: 24px auto; padding: 0 24px; }}
        
        a.paper-card-link {{
            display: block;
            text-decoration: none;
            color: inherit;
            margin-bottom: 20px;
        }}
        .paper-card {{
            background: var(--card-bg);
            border-radius: 16px;
            padding: 24px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.03);
            border: 1px solid var(--border-color);
            transition: border-color 0.2s ease, box-shadow 0.2s ease;
        }}
        a.paper-card-link:hover .paper-card {{
            border-color: rgba(0, 102, 204, 0.4);
            box-shadow: 0 6px 24px rgba(0,102,204,0.08);
        }}
        
        .card-header {{ display: flex; gap: 8px; margin-bottom: 12px; align-items: center; }}
        .badge {{ font-size: 11px; font-weight: 600; padding: 4px 10px; border-radius: 6px; text-transform: uppercase; }}
        .highlight-badge {{ background: #fff3dc; color: #b45309; border: 1px solid #fde68a; }}
        .journal-badge {{ background: #f1f5f9; color: #475569; }}
        .title-ja {{ font-size: 18px; font-weight: 700; margin-bottom: 6px; color: #0f172a; line-height: 1.35; }}
        .title-en {{ font-size: 13px; color: var(--text-sub); margin-bottom: 14px; font-style: italic; }}
        .meta-row {{ display: flex; gap: 16px; font-size: 12px; color: var(--text-sub); margin-bottom: 16px; flex-wrap: wrap; align-items: center; }}
        .pmid-badge {{ color: var(--accent); font-weight: 600; background: #eff6ff; padding: 2px 8px; border-radius: 4px; }}
        .summary-box {{ background: #f8fafc; border-radius: 10px; padding: 14px; font-size: 13.5px; border: 1px solid #f1f5f9; }}
        .summary-item {{ margin-bottom: 6px; color: #334155; }}
        .summary-item:last-child {{ margin-bottom: 0; }}
        .summary-item strong {{ color: #0f172a; }}

        footer {{
            max-width: 1000px;
            margin: 40px auto 0;
            padding: 24px;
            text-align: center;
            border-top: 1px solid var(--border-color);
            color: var(--text-sub);
            font-size: 12px;
        }}
    </style>
</head>
<body>
    <header>
        <div class="header-container">
            <div>
                <div class="site-title">今週の胆膵疾患研究ハイライト</div>
                <div class="sub-title">Pancreatobiliary Weekly Digest ({date_str})</div>
            </div>
            <select onchange="location.href=this.value" class="archive-select">
                {options_html}
            </select>
        </div>
        <nav class="tabs-nav">
            <button class="tab-btn active" onclick="filterCategory('all', this)">すべて</button>
            <button class="tab-btn" onclick="filterCategory('highlight', this)">⭐ TOPハイライト</button>
            <button class="tab-btn" onclick="filterCategory('endo', this)">1. 胆膵内視鏡</button>
            <button class="tab-btn" onclick="filterCategory('pancreas-benign', this)">2. 膵良性疾患</button>
            <button class="tab-btn" onclick="filterCategory('biliary-benign', this)">3. 胆道良性疾患</button>
            <button class="tab-btn" onclick="filterCategory('cancer', this)">4. 膵・胆道悪性疾患</button>
            <button class="tab-btn" onclick="filterCategory('transplant', this)">5. 肝胆膵移植外科</button>
        </nav>
    </header>

    <main id="cards-container">
        {cards_html}
    </main>

    <footer>
        <p>&copy; 2026 Pancreatobiliary Weekly Digest. All rights reserved.</p>
    </footer>

    <script>
        function filterCategory(cat, btn) {{
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            const links = document.querySelectorAll('.paper-card-link');
            links.forEach(link => {{
                if (cat === 'all') {{
                    link.style.display = 'block';
                }} else {{
                    if (link.classList.contains(cat)) {{
                        link.style.display = 'block';
                    }} else {{
                        link.style.display = 'none';
                    }}
                }}
            }});
        }}
    </script>
</body>
</html>"""
    return full_html

# ----------------------------------------------------
# 4. アーカイブ管理とファイル保存
# ----------------------------------------------------
def save_and_manage_archives(analyzed_papers, original_papers, date_display_str, date_file_str):
    os.makedirs("docs/archives", exist_ok=True)
    
    # 既存アーカイブ一覧の取得
    archive_files = sorted(glob.glob("docs/archives/weekly-*.html"), reverse=True)
    archives = []
    for file_path in archive_files[:52]:
        filename = os.path.basename(file_path)
        date_part = filename.replace("weekly-", "").replace(".html", "")
        archives.append({
            "date": date_part,
            "filename": filename
        })

    # 今回のファイルをアーカイブリストの先頭に追加
    current_arch = {"date": date_file_str, "filename": f"weekly-{date_file_str}.html"}
    if not any(a["date"] == date_file_str for a in archives):
        archives.insert(0, current_arch)

    # 1. トップページ (docs/index.html) の生成・保存
    root_html = build_fixed_html(analyzed_papers, original_papers, date_display_str, archives, is_root=True)
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(root_html)

    # 2. 週別アーカイブ (docs/archives/weekly-YYYY-MM-DD.html) の生成・保存
    archive_html = build_fixed_html(analyzed_papers, original_papers, date_display_str, archives, is_root=False)
    archive_path = os.path.join("docs/archives", f"weekly-{date_file_str}.html")
    with open(archive_path, "w", encoding="utf-8") as f:
        f.write(archive_html)

# ----------------------------------------------------
# メイン実行処理
# ----------------------------------------------------
if __name__ == "__main__":
    today = datetime.date.today()
    date_display_str = today.strftime("%Y年%m月%d日週")
    date_file_str = today.strftime("%Y-%m-%d")
    
    print(f"[{date_display_str}] 厳選54誌からの臨床研究論文アーカイブの抽出を開始します...")
    
    papers = fetch_pubmed_papers()
    
    if papers:
        print(f"対象ジャーナルより {len(papers)} 件の厳選臨床論文を取得しました。Geminiで解析中...")
        analyzed_papers = analyze_papers_with_gemini(papers)
        
        print("最新ページおよびアーカイブHTMLを書き換え中...")
        save_and_manage_archives(analyzed_papers, papers, date_display_str, date_file_str)
        print("ウィークリーアップデートが完全成功しました！")
    else:
        print("今週の対象論文が見つかりませんでした。")
