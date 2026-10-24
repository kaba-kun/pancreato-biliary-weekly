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

# ----------------------------------------------------
# 1. PubMedから「臨床研究・原著論文のみ」「指定7日間」を取得
# ----------------------------------------------------
def fetch_pubmed_papers():
    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    
    # 胆膵関連キーワード ＋ 臨床研究限定フィルター ＋ 直近7日間
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
        
        # 簡易雑誌名マッチング (対象リストに含まれているか確認)
        is_target_journal = any(
            target.lower() in journal.lower() or journal.lower() in target.lower() 
            for target in TARGET_JOURNALS
        )
        if not is_target_journal:
            continue

        pmid = article.find(".//PMID").text if article.find(".//PMID") is not None else ""
        title = article.find(".//ArticleTitle").text if article.find(".//ArticleTitle") is not None else ""
        
        # 筆頭著者
        author_list = article.findall(".//AuthorList/Author")
        authors_formatted = "Unknown"
        if author_list:
            first_author = author_list[0]
            last_name = first_author.findtext("LastName") or ""
            initials = first_author.findtext("Initials") or ""
            name_str = f"{last_name} {initials}".strip()
            authors_formatted = f"{name_str} et al." if len(author_list) > 1 else name_str

        # 出版日
        pub_date_elem = article.find(".//Journal/JournalIssue/PubDate")
        pub_date_str = ""
        if pub_date_elem is not None:
            year = pub_date_elem.findtext("Year") or ""
            month = pub_date_elem.findtext("Month") or ""
            day = pub_date_elem.findtext("Day") or ""
            pub_date_str = f"{year}-{month}-{day}".strip("-") if year else (pub_date_elem.findtext("MedlineDate") or "")

        abstract_texts = article.findall(".//AbstractText")
        abstract = " ".join([elem.text for elem in abstract_texts if elem.text])
        
        # 動物実験・基礎研究キーワードの簡易排斥
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
# 2. Gemini APIでApple風UI ＋ カテゴリ・アーカイブ対応HTML生成
# ----------------------------------------------------
def generate_digest_html(papers, date_str, archive_list):
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

    # アーカイブメニューのHTMLドロップダウン生成
    archive_options = '<option value="../index.html">最新号 (最新)</option>'
    for arch in archive_list:
        archive_options += f'<option value="{arch["filename"]}">{arch["date"]}</option>'

    prompt = f"""
あなたは世界最高峰の胆膵外科・内視鏡の臨床研究者であり、AppleやVercelのようなプロダクトデザインを手がけるUIデザイナーです。
以下の{len(papers)}件の最新臨床研究論文（オリジナルアーティクル）から、読者を惹きつける洗練されたウィークリーダッシュボードHTMLを作成してください。

対象期間: {date_str}
論文データ:
{papers}

【デザイン・UIコンセプト（Apple Inspired Minimal UI）】
- **フォント**: System UI (-apple-system, BlinkMacSystemFont, "SF Pro Display", "Inter", sans-serif)
- **カラー**: 
  - 背景: #f5f5f7 (Apple製品ページ調の繊細なグレー)
  - ヘッダー・テキスト: #1d1d1f (ディープブラック)
  - アクセント: #0066cc (Apple Blue)
  - カード: #ffffff (純白、border-radius: 16px、box-shadow: 0 4px 20px rgba(0,0,0,0.04))
- **インタラクティブ・タブバー (重要)**:
  ページ上部にガラス感のある固定タブバーを配置し、JavaScriptでカードの表示/非表示を瞬時に切り替えられるようにしてください。
  タブ項目: 
    * すべて (`data-category="all"`)
    * ⭐ TOPハイライト (`data-category="highlight"`)
    * 1. 胆膵内視鏡 (`data-category="endo"`)
    * 2. 膵良性疾患 (`data-category="pancreas-benign"`)
    * 3. 胆道良性疾患 (`data-category="biliary-benign"`)
    * 4. 膵・胆道悪性腫瘍 (`data-category="cancer"`)
    * 5. 肝胆膵移植外科 (`data-category="transplant"`)

【トップハイライト選定基準】
- 臨床的インパクトが極めて高い臨床試験（RCT、大規模多施設コホート、SNS/学会で話題を呼ぶイノベーティブな研究）3〜4報に `data-category` へ `highlight` と各領域カテゴリの両方を付与し、上部にハイライトバッジを表示してください。

【各論文カードの記載構造】
1. **カードのHTML属性**: `<article class="paper-card" data-category="[カテゴリID]">`
2. **領域・ジャーナルタグ**: 掲載誌名 ＋ 推定Impact Factor (例: *Gastroenterology* [IF ~29.7])
3. **タイトル**: 魅力的で正確な【日本語タイトル】（18px / Bold）、下に英語原題
4. **メタ情報**: 著者名 (Smith J et al.) | 出版日 | PMIDバッジ (PubMedリンク)
5. **詳細臨床要約 (構造化形式)**:
   - **デザイン・対象**: (例: 多施設ランダム化比較試験 [RCT] / 320例)
   - **主要結果**: (主要エンドポイントの数値や有意差、効果を明瞭に)
   - **臨床的要点**: (明日の診療やガイドラインに与えるインパクト)

【ヘッダーアーカイブドロップダウン】
ヘッダー右上に以下のドロップダウンHTMLを組み込んでください：
`<select onchange="location.href=this.value" class="archive-select">{archive_options}</select>`

【JavaScript埋め込み】
タブをクリックした際に、対応する `data-category` を持つ `.paper-card` のみを表示（"all" の場合は全表示）するシンプルなJSコードを HTML内の `<script>` に含めてください。

※ `<!DOCTYPE html>` から始まる完全なHTMLコードのみを出力してください。解説テキストや ```html のようなマークダウンは含めないでください。
"""

    model_name = 'gemini-3.8-flash'
    for attempt in range(3):
        try:
            print(f"モデル [{model_name}] で生成を実行中... (試行 {attempt + 1}/3)")
            response = client.models.generate_content(
                model=model_name,
                contents=prompt
            )
            html_text = response.text.strip()
            if html_text.startswith("```html"):
                html_text = html_text[7:]
            if html_text.endswith("```"):
                html_text = html_text[:-3]
            return html_text.strip()
        except Exception as e:
            print(f"通信エラーが発生しました: {e}")
            time.sleep(5)

    raise RuntimeError("AIモデルの呼び出しに失敗しました。")

# ----------------------------------------------------
# 3. アーカイブ管理とファイル保存
# ----------------------------------------------------
def save_and_manage_archives(html_content, date_file_str):
    os.makedirs("docs/archives", exist_ok=True)
    
    # 1. 週ごとの個別アーカイブファイルとして保存
    archive_filename = f"weekly-{date_file_str}.html"
    archive_path = os.path.join("docs/archives", archive_filename)
    with open(archive_path, "w", encoding="utf-8") as f:
        f.write(html_content)
        
    # 2. トップページ (docs/index.html) としても最新版を保存
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(html_content)

def get_existing_archives():
    archive_files = sorted(glob.glob("docs/archives/weekly-*.html"), reverse=True)
    archives = []
    for file_path in archive_files[:52]: # 過去1年分(52週)まで保持
        filename = os.path.basename(file_path)
        date_part = filename.replace("weekly-", "").replace(".html", "")
        archives.append({
            "date": date_part,
            "filename": f"archives/{filename}"
        })
    return archives

# ----------------------------------------------------
# メイン実行処理
# ----------------------------------------------------
if __name__ == "__main__":
    today = datetime.date.today()
    date_display_str = today.strftime("%Y年%m月%d日週")
    date_file_str = today.strftime("%Y-%m-%d")
    
    print(f"[{date_display_str}] 厳選54誌からの臨床研究論文アーカイブの抽出を開始します...")
    
    # 既存の過去アーカイブ一覧を取得
    existing_archives = get_existing_archives()
    
    papers = fetch_pubmed_papers()
    if papers:
        print(f"対象ジャーナルより {len(papers)} 件の厳選臨床論文を取得しました。Apple風UIで生成中...")
        html_content = generate_digest_html(papers, date_display_str, existing_archives)
        
        print("最新ページ (docs/index.html) およびアーカイブを更新中...")
        save_and_manage_archives(html_content, date_file_str)
        print("ウィークリーアップデートが正常に完了しました！")
    else:
        print("今週の対象論文が見つかりませんでした。")
