import os
import time
import datetime
import requests
import xml.etree.ElementTree as ET
from google import genai

# ----------------------------------------------------
# 1. PubMedから詳細な論文データを取得 (新5領域のキーワードを追加)
# ----------------------------------------------------
def fetch_pubmed_papers():
    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    # IPMN, AIP, PSC, IgG4, PNET, 移植キーワードを拡充
    query = '("pancreatitis"[Title/Abstract] OR "pancreatic"[Title/Abstract] OR "biliary"[Title/Abstract] OR "ERCP"[Title/Abstract] OR "EUS"[Title/Abstract] OR "cholangiocarcinoma"[Title/Abstract] OR "cholangitis"[Title/Abstract] OR "choledocholithiasis"[Title/Abstract] OR "gallstone"[Title/Abstract] OR "IPMN"[Title/Abstract] OR "PSC"[Title/Abstract] OR "IgG4"[Title/Abstract] OR "neuroendocrine"[Title/Abstract] OR "pancreas transplantation"[Title/Abstract] OR "liver transplantation"[Title/Abstract]) AND ("last 7 days"[PDat])'
    
    search_res = requests.get(f"{base_url}/esearch.fcgi", params={
        "db": "pubmed", "term": query, "retmode": "json", "retmax": 35
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
        pmid = article.find(".//PMID").text if article.find(".//PMID") is not None else ""
        title = article.find(".//ArticleTitle").text if article.find(".//ArticleTitle") is not None else ""
        journal = article.find(".//Journal/Title").text if article.find(".//Journal/Title") is not None else ""
        
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
            if year:
                pub_date_str = f"{year}-{month}-{day}".strip("-")
            else:
                pub_date_str = pub_date_elem.findtext("MedlineDate") or ""

        abstract_texts = article.findall(".//AbstractText")
        abstract = " ".join([elem.text for elem in abstract_texts if elem.text])
        
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
# 2. Gemini APIで極上のミニマルHTMLを生成
# ----------------------------------------------------
def generate_digest_html(papers, date_str):
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

    prompt = f"""
あなたは胆膵領域の世界的トップ研究者兼、センスの突出したWebデザイナーです。
以下の{len(papers)}件の最新論文から、臨床的インパクトが高い重要な論文（原則推定IF 3.0以上相当）を厳選し、超シンプルで洗練されたモダンUI（1ページ完結ダッシュボード）を作成してください。

対象日付: {date_str}
論文データ:
{papers}

【Webデザイン・スタイルの絶対要件】
- **Favicon**: `<head>` にスマートな医療SVG Faviconを埋め込む：
  `<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>🔬</text></svg>">`
- **UIコンセプト**: AppleやVercelのように極めてシンプル、モダン、洗練されたインターフェース。不要な枠線や濃いグラデーション、ゴチャついた要素は一切禁止。
- **配色**: 
  - 背景: #f9fafb (極小の温かみがあるライトグレー)
  - テキスト: #09090b (深いオプシディアン)
  - サブテキスト: #71717a (スレート)
  - カード背景: #ffffff (純白)
  - アクセント: #4f46e5 (インディゴブルー)
- **フォント＆カード**: `-apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", sans-serif` を使用。カードは `border-radius: 12px; border: 1px solid #e4e4e7;`。

【カテゴリ分類 (必ず以下の5領域のみに分類)】
1. **胆膵内視鏡**
2. **膵良性疾患** (急性膵炎/慢性膵炎/自己免疫性膵炎/IPMN等嚢胞性腫瘤など)
3. **胆道良性疾患** (胆管炎/PSC/総胆管結石/IgG4-SCなど)
4. **膵・胆道悪性腫瘍** (膵癌/胆管がん/PNETなど)
5. **肝胆膵移植外科**

【各論文カードの記載ルール】
1. **タイトル**: わかりやすく簡潔な【日本語タイトル】（フォントサイズ16px/Bold）を提示し、その下に英語原題を小さく添える。
2. **メタ情報ピルバッジ (1行にスッキリ横並び表示)**:
   - 著者名 (例: Smith J et al.)
   - 出版日 (例: 2026-10-15)
   - 掲載誌 ＋ 推定IF (例: Endoscopy [IF ~11.5])
   - PMIDリンク (https://pubmed.ncbi.nlm.nih.gov/PMID/ へ飛ぶバッジ)
3. **要約**: **【必ず日本語1文（一文のみ）】**で、この研究が結論づけた臨床的要点をズバッと記述する。長文や箇条書きは不可。

※ `<!DOCTYPE html>` から始まる完全なHTMLコードのみを出力してください。解説文や ```html マークダウンは絶対に含めないでください。
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
# 3. HTMLファイルの保存
# ----------------------------------------------------
def save_html_for_web(html_content):
    os.makedirs("docs", exist_ok=True)
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(html_content)

# ----------------------------------------------------
# メイン実行処理
# ----------------------------------------------------
if __name__ == "__main__":
    today_str = datetime.date.today().strftime("%Y年%m月%d日")
    print(f"[{today_str}] 論文情報の収集を開始します...")
    
    papers = fetch_pubmed_papers()
    if papers:
        print(f"{len(papers)} 件の論文を取得しました。極上ミニマルWebデザインで生成中...")
        html_content = generate_digest_html(papers, today_str)
        
        print("Webページ (docs/index.html) を書き換え中...")
        save_html_for_web(html_content)
        print("最新デザインでの更新が完了しました！")
    else:
        print("新しい論文が見つかりませんでした。")
