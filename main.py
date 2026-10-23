import os
import datetime
import requests
import xml.etree.ElementTree as ET
from google import genai
from google.genai import types
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ----------------------------------------------------
# 1. PubMedから論文データ取得
# ----------------------------------------------------
def fetch_pubmed_papers():
    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    # 過去7日間の胆膵系論文を抽出するクエリ
    query = '("pancreatitis"[Title/Abstract] OR "pancreatic"[Title/Abstract] OR "biliary"[Title/Abstract] OR "ERCP"[Title/Abstract] OR "EUS"[Title/Abstract] OR "cholangiocarcinoma"[Title/Abstract]) AND ("last 7 days"[PDat])'
    
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
# 2. Gemini APIでHTMLコンテンツ作成
# ----------------------------------------------------
def generate_digest_html(papers, date_str):
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    prompt = f"""
あなたは胆膵疾患領域のトップ専門医・研究者です。
以下の{len(papers)}件の論文データ（対象期間：直近1週間）を解析し、Webサイトおよびメール配信用の「今週の胆膵疾患研究ハイライト」HTMLを作成してください。

対象日付: {date_str}
論文データ:
{papers}

【デザイン・構造の要件】
1. モダンで清潔感のある医療系デザイン（レスポンシブ対応、CSSはすべて <style> タグ内に記述）。
2. 全体構成：
   - ヘッダー：「今週の胆膵疾患研究ハイライト」（対象期間：{date_str}）
   - 今週のトップハイライト (Top 3~4報)：臨床的インパクトが高いものを厳選し、簡潔なカード形式で提示。
   - 領域別研究ハイライト：以下のようなカテゴリに分類して配置。
     * 胆膵内視鏡・ERCP・EUS
     * 急性膵炎・慢性膵炎・総胆管結石・胆管炎など胆膵の良性疾患
     * 胆道がん・膵がん・腫瘍など胆膵の悪性疾患
     * 肝移植・IgG4関連疾患・その他
3. 各論文の掲載形式：
   - 論文タイトル（英語 ＋ 日本語訳）
   - 掲載誌・PMID（https://pubmed.ncbi.nlm.nih.gov/PMID/ への直リンク付き）
   - 日本語要約（背景・主要結果・臨床的意義・研究の限界を2〜3文で明記）
   - 英語要約（1〜2文のキーポイント）

※ <!DOCTYPE html> から始まる完全なHTMLコードのみを出力してください。余計な解説テキストやバックティック(```html)は含めないでください。
"""
    
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt
    )
    
    # 余分なマークダウン装飾がある場合に除去
    html_text = response.text.strip()
    if html_text.startswith("```html"):
        html_text = html_text[7:]
    if html_text.endswith("```"):
        html_text = html_text[:-3]
    return html_text.strip()

# ----------------------------------------------------
# 3. HTMLファイルの保存（GitHub Pages用）
# ----------------------------------------------------
def save_html_for_web(html_content):
    os.makedirs("docs", exist_ok=True)
    # 常に最新版として index.html に保存（GitHub Pagesのトップページになる）
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(html_content)

# ----------------------------------------------------
# 4. メール送信
# ----------------------------------------------------
def send_email(html_content, date_str):
    sender_email = os.environ["SENDER_EMAIL"]
    sender_password = os.environ["SENDER_PASSWORD"]
    receiver_email = os.environ["RECEIVER_EMAIL"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"【週報】今週の胆膵疾患研究ハイライト ({date_str})"
    msg["From"] = sender_email
    msg["To"] = receiver_email

    msg.attach(MIMEText(html_content, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, receiver_email, msg.as_string())

# ----------------------------------------------------
# メイン実行処理
# ----------------------------------------------------
if __name__ == "__main__":
    today_str = datetime.date.today().strftime("%Y年%m月%d日")
    print(f"[{today_str}] 論文情報の収集を開始します...")
    
    papers = fetch_pubmed_papers()
    if papers:
        print(f"{len(papers)} 件の論文が見つかりました。AIによるHTML要約を生成中...")
        html_content = generate_digest_html(papers, today_str)
        
        print("Web公開用HTML (docs/index.html) を更新中...")
        save_html_for_web(html_content)
        
        print("メールを送信中...")
        send_email(html_content, today_str)
        print("すべての処理が完了しました！")
    else:
        print("該当する新しい論文が見つかりませんでした。")
