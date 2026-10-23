import os
import datetime
import requests
import xml.etree.ElementTree as ET
from google import genai

# ----------------------------------------------------
# 1. PubMedから論文データ取得 (胆管炎・結石のキーワードを追加)
# ----------------------------------------------------
def fetch_pubmed_papers():
    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    # 胆管炎 (cholangitis)、総胆管結石 (choledocholithiasis / gallstone) を追加
    query = '("pancreatitis"[Title/Abstract] OR "pancreatic"[Title/Abstract] OR "biliary"[Title/Abstract] OR "ERCP"[Title/Abstract] OR "EUS"[Title/Abstract] OR "cholangiocarcinoma"[Title/Abstract] OR "cholangitis"[Title/Abstract] OR "choledocholithiasis"[Title/Abstract] OR "gallstone"[Title/Abstract]) AND ("last 7 days"[PDat])'
    
    search_res = requests.get(f"{base_url}/esearch.fcgi", params={
        "db": "pubmed", "term": query, "retmode": "json", "retmax": 25
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
        
        abstract_texts = article.findall(".//AbstractText")
        abstract = " ".join([elem.text for elem in abstract_texts if elem.text])
        
        papers.append({
            "pmid": pmid,
            "title": title,
            "journal": journal,
            "abstract": abstract
        })
    return papers

# ----------------------------------------------------
# 2. Gemini APIでスタイリッシュなHTMLを作成
# ----------------------------------------------------
def generate_digest_html(papers, date_str):
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

    prompt = f"""
あなたは胆膵領域のトップ臨床医・研究者です。
以下の{len(papers)}件の最新論文データから、世界水準のモダンで美しいWebダッシュボード風HTML（1ページ完結）を作成してください。

対象日付: {date_str}
論文データ:
{papers}

【デザインコンセプト＆カラー】
- **スタイル**: AppleやNote、Stripeのような極めてシンプルで洗練されたモダンUI。ゴチャついたイラストや太すぎる枠線は使わない。
- **配色**: 背景 #f8fafc (超淡いグレー)、メイン文字 #0f172a (ダークスレート)、アクセント #2563eb (ロイヤルブルー)、カード背景 #ffffff。
- **レスポンシブ**: PCでは美しいカードレイアウト、スマホでは余白を十分にとった1カラムの読みやすいリスト。

【コンテンツ構成】
1. **Header**:
   - サイトタイトル「PANCREATOBILIARY WEEKLY DIGEST」
   - サブタイトル「今週の胆膵疾患研究ハイライト ({date_str})」
2. **Top Highlights (今週の要注目 3〜4報)**:
   - 臨床インパクトが高い重要論文を最上部に大きなカードで配置。
   - 「なぜ重要か」を一言で添える。
3. **Category Sections (以下の5領域に明確に分類)**:
   - 1. 胆膵内視鏡・ERCP・EUS
   - 2. 胆管炎・総胆管結石・良性胆道疾患
   - 3. 急性・慢性膵炎
   - 4. 胆道がん・膵がん・腫瘍
   - 5. 肝移植・IgG4関連疾患・その他

【各論文カードの記載フォーマット】
- **タイトル**: わかりやすい【日本語タイトル】を16px/Boldで強調し、下に英語原題を小さく添える。
- **メタバッジ**: 掲載誌名、PMID (https://pubmed.ncbi.nlm.nih.gov/PMID/ へのリンクバッジ)。
- **要約本文**: 箇条書き風にコンパクトに整形（・背景/目的 ・主な結果 ・臨床的メッセージ）。ダラダラ長文にしない。

※ `<!DOCTYPE html>` から始まる完全なHTMLコードのみを出力してください。解説テキストや ```html のようなマークダウンタグは一切含めないでください。
"""
    
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt
    )
    
    html_text = response.text.strip()
    if html_text.startswith("```html"):
        html_text = html_text[7:]
    if html_text.endswith("```"):
        html_text = html_text[:-3]
    return html_text.strip()

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
        print(f"{len(papers)} 件の論文を取得しました。最高品質のWebデザインで生成中...")
        html_content = generate_digest_html(papers, today_str)
        
        print("Webページ (docs/index.html) を書き換え中...")
        save_html_for_web(html_content)
        print("最新デザインでの更新が完了しました！")
    else:
        print("新しい論文が見つかりませんでした。")
