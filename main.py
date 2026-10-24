import os
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

# カテゴリーのソート順定義
CATEGORY_ORDER = {
    "endo": 1,
    "pancreas-benign": 2,
    "biliary-benign": 3,
    "cancer": 4,
    "case-report": 5
}

# ----------------------------------------------------
# 1. PubMedから「指定7日間」の論文を取得 (POST方式)
# ----------------------------------------------------
def fetch_pubmed_papers():
    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    headers = {"User-Agent": "PancreatobiliaryDigest/1.0"}
    
    term_keywords = '("pancreatitis"[Title/Abstract] OR "pancreatic cancer"[Title/Abstract] OR "pancreatic ductal adenocarcinoma"[Title/Abstract] OR "PDAC"[Title/Abstract] OR "pancreatic carcinoma"[Title/Abstract] OR "pancreatic neuroendocrine tumor"[Title/Abstract] OR "PanNET"[Title/Abstract] OR "IPMN"[Title/Abstract] OR "intraductal papillary mucinous neoplasm"[Title/Abstract] OR "MCN"[Title/Abstract] OR "mucinous cystic neoplasm"[Title/Abstract] OR "SCN"[Title/Abstract] OR "serous cystic neoplasm"[Title/Abstract] OR "serous cystadenoma"[Title/Abstract] OR "pancreatic cyst"[Title/Abstract] OR "pancreatic cystic"[Title/Abstract] OR "autoimmune pancreatitis"[Title/Abstract] OR "AIP"[Title/Abstract] OR "pancreatic fistula"[Title/Abstract] OR "POPF"[Title/Abstract] OR "postoperative pancreatic fistula"[Title/Abstract] OR "pancreatic duct stricture"[Title/Abstract] OR "biliary"[Title/Abstract] OR "cholangiocarcinoma"[Title/Abstract] OR "biliary tract cancer"[Title/Abstract] OR "gallbladder cancer"[Title/Abstract] OR "gallbladder carcinoma"[Title/Abstract] OR "gallbladder disease"[Title/Abstract] OR "cholangitis"[Title/Abstract] OR "cholecystitis"[Title/Abstract] OR "choledocholithiasis"[Title/Abstract] OR "common bile duct stones"[Title/Abstract] OR "gallstone"[Title/Abstract] OR "PSC"[Title/Abstract] OR "primary sclerosing cholangitis"[Title/Abstract] OR "IgG4-related sclerosing cholangitis"[Title/Abstract] OR "choledochal cyst"[Title/Abstract] OR "biliary stricture"[Title/Abstract] OR "ampullary carcinoma"[Title/Abstract] OR "ampullary cancer"[Title/Abstract] OR "cancer of the ampulla of vater"[Title/Abstract] OR "ampullary adenoma"[Title/Abstract] OR "papillary carcinoma"[Title/Abstract] OR "papillary adenoma"[Title/Abstract] OR "papillary tumor"[Title/Abstract] OR "papilla of vater"[Title/Abstract] OR "papillectomy"[Title/Abstract] OR "endoscopic papillectomy"[Title/Abstract] OR "ERCP"[Title/Abstract] OR "endoscopic retrograde cholangiopancreatography"[Title/Abstract] OR "EUS"[Title/Abstract] OR "endoscopic ultrasound"[Title/Abstract] OR "endoscopic ultrasonography"[Title/Abstract] OR "FNA"[Title/Abstract] OR "fine needle aspiration"[Title/Abstract] OR "fine-needle aspiration"[Title/Abstract] OR "FNB"[Title/Abstract] OR "fine needle biopsy"[Title/Abstract] OR "fine-needle biopsy"[Title/Abstract] OR "EUS-TA"[Title/Abstract] OR "tissue acquisition"[Title/Abstract] OR "EUS-guided"[Title/Abstract] OR "sphincterotomy"[Title/Abstract] OR "EST"[Title/Abstract] OR "endoscopic sphincterotomy"[Title/Abstract] OR "EPBD"[Title/Abstract] OR "endoscopic papillary balloon dilation"[Title/Abstract] OR "EPLBD"[Title/Abstract] OR "endoscopic papillary large balloon dilation"[Title/Abstract] OR "cholangioscopy"[Title/Abstract] OR "pancreatoscopy"[Title/Abstract] OR "biliary stent"[Title/Abstract] OR "biliary stenting"[Title/Abstract] OR "pancreatic stent"[Title/Abstract] OR "pancreatic stenting"[Title/Abstract] OR "biliary drainage"[Title/Abstract] OR "pancreatic drainage"[Title/Abstract])'
    
    date_filter = 'AND ("last 7 days"[PDat])'
    query = f"{term_keywords} {date_filter}"
    
    search_res = requests.post(f"{base_url}/esearch.fcgi", data={
        "db": "pubmed", "term": query, "retmode": "json", "retmax": 80
    }, headers=headers)
    
    if search_res.status_code != 200:
        print(f"PubMed Search Error: HTTP {search_res.status_code}")
        return []
        
    id_list = search_res.json().get("esearchresult", {}).get("idlist", [])
    if not id_list:
        return []

    fetch_res = requests.post(f"{base_url}/efetch.fcgi", data={
        "db": "pubmed", "id": ",".join(id_list), "retmode": "xml"
    }, headers=headers)
    
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
        abstract = " ".join([elem.text for elem in abstract_texts if elem.text]).strip()
        
        lower_abstract = abstract.lower()
        if not abstract or "no abstract available" in lower_abstract or len(abstract) < 50:
            continue

        if "mouse model" in lower_abstract or "mice" in lower_abstract or "rat model" in lower_abstract or "in vitro" in lower_abstract:
            continue

        papers.append({
            "id": len(papers),
            "pmid": pmid,
            "title": title,
            "journal": journal,
            "author": authors_formatted,
            "pub_date": pub_date_str,
            "abstract": abstract
        })
        
    return papers

# ----------------------------------------------------
# 2. Gemini APIで論文の解析・日本語要約・カテゴリ分類を行う
# ----------------------------------------------------
def analyze_papers_with_gemini(papers):
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

    simplified_papers = [
        {"id": p["id"], "title": p["title"], "journal": p["journal"], "abstract": p["abstract"]}
        for p in papers
    ]

    prompt = f"""
あなたは世界最高峰の胆膵内科ならびに胆膵内視鏡の臨床医かつ臨床研究者です。
以下の論文データリストから、各論文の日本語タイトル、カテゴリ分類、研究デザイン、主要結果、臨床的要点を抽出し、指定のJSONフォーマットで出力してください。

論文データ:
{simplified_papers}

【JSON出力フォーマット (厳守)】
以下のキーを持つJSON配列 (Array) の形式で出力してください：
[
  {{
    "id": 論文データにある数値ID (0, 1, 2...),
    "title_ja": "魅力的で正確な日本語タイトル",
    "title_en": "英語原題",
    "category": "カテゴリID (endo, pancreas-benign, biliary-benign, cancer, case-report のいずれか)",
    "is_highlight": trueまたはfalse (最重要3~4報のみtrue),
    "study_design": "研究デザイン・対象症例数 (例: 多施設RCT / 320例 / 症例報告)",
    "results": "主要結果 (主要エンドポイントや数値、症例概要)",
    "takeaway": "臨床的要点 (日常診療への影響・教訓)"
  }}
]

【カテゴリID定義】
- endo: 胆膵内視鏡 (ERCP, EUS, FNA/FNB, EUS-TA, EST, EPBD, 乳頭切除, ステント, ドレナージ等)
- pancreas-benign: 膵良性疾患 (急性・慢性・自己免疫性膵炎、IPMN, MCN, SCN等嚢胞性腫瘤、膵液瘻等)
- biliary-benign: 胆道良性疾患 (胆管炎、胆嚢炎、PSC、総胆管結石、IgG4-SC、胆道狭窄等)
- cancer: 膵・胆道悪性疾患 (膵癌, PDAC, PanNET, 胆管がん、胆嚢癌、十二指腸乳頭部癌/腺腫等)
- case-report: 症例報告 (臨床的に教訓的・希少・貴重な症例報告、Case Report、Case Series等)

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
            
            analyzed = json.loads(raw_text.strip())
            # カテゴリー順にソート（1: endo -> 2: pancreas-benign -> 3: biliary-benign -> 4: cancer -> 5: case-report）
            analyzed.sort(key=lambda x: CATEGORY_ORDER.get(x.get("category", ""), 99))
            return analyzed
            
        except Exception as e:
            wait_time = (attempt + 1) * 10
            print(f"一時的な通信エラー ({e})。{wait_time}秒後に再試行します...")
            time.sleep(wait_time)

    raise RuntimeError("AIモデルの呼び出しに失敗しました。")

# ----------------------------------------------------
# 3. 完全固定のApple風HTMLテンプレートをレンダリングする
# ----------------------------------------------------
def build_fixed_html(analyzed_papers, original_papers, date_str, archive_list, is_root=True):
    top_link = "index.html" if is_root else "../index.html"
    
    archive_options = []
    if is_root:
        archive_options.append('<option value="index.html" selected>最新号 (最新)</option>')
        for arch in archive_list:
            archive_options.append(f'<option value="archives/{arch["filename"]}">{arch["date"]}</option>')
    else:
        archive_options.append('<option value="../index.html">最新号 (最新)</option>')
        for arch in archive_list:
            if arch["date"] in date_str:
                archive_options.append(f'<option value="{arch["filename"]}" selected>{arch["date"]}</option>')
            else:
                archive_options.append(f'<option value="{arch["filename"]}">{arch["date"]}</option>')

    options_html = "\n".join(archive_options)

    id_to_orig = {p["id"]: p for p in original_papers}

    cards_html = ""
    for p in analyzed_papers:
        paper_id = p.get("id")
        orig_data = id_to_orig.get(paper_id, {})
        
        pmid = orig_data.get("pmid", "")
        pubmed_url = f"[https://pubmed.ncbi.nlm.nih.gov/](https://pubmed.ncbi.nlm.nih.gov/){pmid}/" if pmid else "#"
        
        journal = orig_data.get("journal", "")
        author = orig_data.get("author", "")
        pub_date = orig_data.get("pub_date", "")

        highlight_badge = '<span class="badge highlight-badge">⭐ TOP HIGHLIGHT</span>' if p.get("is_highlight") else ''
        category_class = f'{p.get("category", "endo")}'
        if p.get("is_highlight"):
            category_class += " highlight"

        cards_html += f"""
        <article class="paper-card {category_class}">
            <div class="card-header">
                {highlight_badge}
                <span class="badge journal-badge">{journal}</span>
            </div>
            <h2 class="title-ja">{p.get("title_ja", "")}</h2>
            <p class="title-en">{p.get("title_en", "")}</p>
            <div class="meta-row">
                <span>👤 {author}</span>
                <span>📅 {pub_date}</span>
                <a href="{pubmed_url}" target="_blank" rel="noopener noreferrer" class="pmid-link">PMID: {pmid} ↗</a>
            </div>
            <div class="summary-box">
                <div class="summary-item"><strong>研究デザイン:</strong> {p.get("study_design", "")}</div>
                <div class="summary-item"><strong>主要結果:</strong> {p.get("results", "")}</div>
                <div class="summary-item"><strong>臨床的要点:</strong> {p.get("takeaway", "")}</div>
            </div>
        </article>
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
        .site-title-link {{
            text-decoration: none;
            color: inherit;
        }}
        .site-title-link:hover .site-title {{
            color: var(--accent);
        }}
        .site-title {{ font-size: 20px; font-weight: 700; letter-spacing: -0.02em; color: var(--text-main); transition: color 0.2s ease; }}
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
        
        .paper-card {{
            background: var(--card-bg);
            border-radius: 16px;
            padding: 24px;
            margin-bottom: 20px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.03);
            border: 1px solid var(--border-color);
            transition: border-color 0.2s ease, box-shadow 0.2s ease;
        }}
        .paper-card:hover {{
            border-color: rgba(0, 102, 204, 0.3);
            box-shadow: 0 6px 24px rgba(0,0,0,0.06);
        }}
        
        .card-header {{ display: flex; gap: 8px; margin-bottom: 12px; align-items: center; }}
        .badge {{ font-size: 11px; font-weight: 600; padding: 4px 10px; border-radius: 6px; text-transform: uppercase; }}
        .highlight-badge {{ background: #fff3dc; color: #b45309; border: 1px solid #fde68a; }}
        .journal-badge {{ background: #f1f5f9; color: #475569; }}
        .title-ja {{ font-size: 18px; font-weight: 700; margin-bottom: 6px; color: #0f172a; line-height: 1.35; }}
        .title-en {{ font-size: 13px; color: var(--text-sub); margin-bottom: 14px; font-style: italic; }}
        .meta-row {{ display: flex; gap: 16px; font-size: 12px; color: var(--text-sub); margin-bottom: 16px; flex-wrap: wrap; align-items: center; }}
        
        .pmid-link {{
            color: var(--accent);
            font-weight: 600;
            background: #eff6ff;
            padding: 3px 10px;
            border-radius: 6px;
            text-decoration: none;
            transition: background 0.2s ease;
        }}
        .pmid-link:hover {{
            background: #dbeafe;
            text-decoration: underline;
        }}

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
                <a href="{top_link}" class="site-title-link">
                    <div class="site-title">今週の胆膵疾患研究ハイライト</div>
                </a>
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
            <button class="tab-btn" onclick="filterCategory('case-report', this)">5. 症例報告</button>
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

            const cards = document.querySelectorAll('.paper-card');
            cards.forEach(card => {{
                if (cat === 'all') {{
                    card.style.display = 'block';
                }} else {{
                    if (card.classList.contains(cat)) {{
                        card.style.display = 'block';
                    }} else {{
                        card.style.display = 'none';
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
    
    archive_files = sorted(glob.glob("docs/archives/weekly-*.html"), reverse=True)
    archives = []
    for file_path in archive_files[:52]:
        filename = os.path.basename(file_path)
        date_part = filename.replace("weekly-", "").replace(".html", "")
        archives.append({
            "date": date_part,
            "filename": filename
        })

    current_arch = {"date": date_file_str, "filename": f"weekly-{date_file_str}.html"}
    if not any(a["date"] == date_file_str for a in archives):
        archives.insert(0, current_arch)

    root_html = build_fixed_html(analyzed_papers, original_papers, date_display_str, archives, is_root=True)
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(root_html)

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
