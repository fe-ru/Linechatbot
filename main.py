import os
from dotenv import load_dotenv
import openai
import pymysql
import traceback
import logging
from datetime import datetime, timedelta
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FlexSendMessage, QuickReply, QuickReplyButton, MessageAction, CarouselContainer

app = Flask(__name__)
#create database and table if not exsists
#create_database_and_table()

#ログレベルの設定
logging.basicConfig(level=logging.DEBUG)

LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
MYSQL_HOST = os.getenv('MYSQL_HOST')
MYSQL_USER = os.getenv('MYSQL_USER')
MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD')
MYSQL_DATABASE = os.getenv('MYSQL_DATABASE')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
openai_api_key = OPENAI_API_KEY   


#テンプレ質問、テンプレ解答
template_list_a = {
    '使い方': '以下のテンプレートのように質問してみてください。\n#質問教科・単元\n数学、1次方程式\n\n#質問したい内容\n2x-1=4の解き方がわからない\n質問テンプレートボタンを押すと、テンプレートが表示されます。',
    '質問テンプレート': '#質問したい教科・単元\n（ここに質問したい教科・単元を入力）\n\n#質問したい内容\n（ここに質問したい内容を入力）'
}

#テンプレ質問を言い換えるリスト
template_list_b = {
    '問題を出して': '直前に質問した内容の類題を5題出して下さい。回答は出力しないでください。',
    '答えを教えて':'先ほどの問題の答えと解説を出力して下さい。',
    'もっとわかりやすく説明をして': '少し説明の仕方が難しいです。中学生にもわかるように説明してください'
}

def get_db_connection():
    try:
        # データベース接続情報をログに出力
        #logging.debug(f"DB Connection Info: host={MYSQL_HOST}, user={MYSQL_USER}, password={MYSQL_PASSWORD}, dbname={MYSQL_DATABASE}")

        # データベース接続処理
        connection = pymysql.connect(
            host=MYSQL_HOST,
            user=MYSQL_USER,
            port=3306,
            password=MYSQL_PASSWORD,
            db=MYSQL_DATABASE,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
        return connection
    except Exception as e:
        logging.error("Failed to connect to the database: %s", e)
        raise

def is_user_limited(user_id):
    connection = get_db_connection()
    cursor = connection.cursor()
    
    start_date = datetime.now().date()
    end_date = start_date + timedelta(days=1)

    cursor.execute(
        """
        SELECT COUNT(*) FROM questions_answers
        WHERE user_id = %s AND created_at >= %s AND created_at < %s
        """,
        (user_id, start_date, end_date)
    )

    result = cursor.fetchone()
    cursor.close()
    connection.close()

    if result is None:
        return False
    else:
        count = int(result['COUNT(*)'])
        return count >= 5




def save_question_and_answer(user_id, question, answer):
    logging.debug("save_question_and_answer called")
    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:
            sql = "INSERT INTO `questions_answers` (`user_id`, `question`, `answer`, `created_at`) VALUES (%s, %s, %s, %s)"
            cursor.execute(sql, (user_id, question, answer, datetime.now()))

        connection.commit()
    finally:
        connection.close()



def get_previous_questions_and_answers(user_id, limit=4):
    connection = get_db_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT question, answer FROM questions_answers
        WHERE user_id = %s
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (user_id, limit)
    )

    results = cursor.fetchall()
    cursor.close()
    connection.close()

    formatted_results = []
    for result in results:
        formatted_question = str(result['question'])
        formatted_answer = str(result['answer'])
        formatted_results.append((formatted_question, formatted_answer))
    logging.debug(f"formatted_results: {formatted_results}")
    return formatted_results[::-1]  # ここでリストを逆順に



def get_answer(user_id, question):
    if question == "使い方を見る":
        return "flex", None
    elif question in template_list_a:
        return "text", template_list_a[question]
    elif question in template_list_b:
        question = template_list_b[question]
        previous_qa = get_previous_questions_and_answers(user_id)
        messages = []
        for i, (q, a) in enumerate(previous_qa):
            messages.append({"role": "user", "content": f"{len(previous_qa) - i}個前の質問: {q}"})
            messages.append({"role": "assistant", "content": f"{len(previous_qa) - i}個前の解答: {a}"})
        messages.append( {"role": "system", "content": "you are a helpful assistant"})
        messages.append({"role": "user", "content": f"今回の質問{question}"})
        #logging.debug(f"messages: {messages}")
        res = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=messages
        )
        return "text", res["choices"][0]["message"]["content"]        
    else:
        previous_qa = get_previous_questions_and_answers(user_id)
        messages = []
        for i, (q, a) in enumerate(previous_qa):
            messages.append({"role": "user", "content": f"{len(previous_qa) - i}個前の質問: {q}"})
            messages.append({"role": "assistant", "content": f"{len(previous_qa) - i}個前の解答: {a}"})
        messages.append( {"role": "system", "content": "you are a helpful assistant"})
        messages.append({"role": "user", "content": f"今回の質問{question}"})
        #logging.debug(f"messages: {messages}")
        res = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=messages
        )
        return "text", res["choices"][0]["message"]["content"]

flex_message_content1 = {
    "type": "bubble",
    "hero": {
        "type": "image",
        "url": "https://challenge-room-school.com/wp-content/uploads/2023/01/HP_お問い合わせ_カウンセリング750-×-700-px-1.png",
        "size": "full",
        "aspectRatio": "20:13",
        "aspectMode": "cover",
        "action": {
            "type": "uri",
            "uri": "https://challenge-room-school.com/counseling/"
        }
    },
    "body": {
        "type": "box",
        "layout": "vertical",
        "contents": [
            {
                "type": "text",
                "text": "プロ講師に勉強相談をする",
                "weight": "bold",
                "size": "xl"
            },
            {
                "type": "box",
                "layout": "vertical",
                "margin": "xs",
                "contents": [
                    {
                        "type": "box",
                        "layout": "baseline",
                        "spacing": "sm",
                        "contents": [
                            {
                                "type": "text",
                                "text": "効率的な勉強法を知って、短期間で成績を上げよう",
                                "wrap": True,
                                "color": "#666666",
                                "size": "sm",
                                "flex": 5
                            }
                        ]
                    }
                ]
            }
        ]
    },
    "footer": {
        "type": "box",
        "layout": "vertical",
        "spacing": "sm",
        "contents": [
            {
                "type": "button",
                "style": "link",
                "height": "sm",
                "action": {
                    "type": "uri",
                    "label": "詳しく見る",
                    "uri": "https://sample.com"
                }
            }
        ],
        "flex": 0
    }
}

carousel_contents = CarouselContainer(contents=[flex_message_content1])
flex_message_carousel = FlexSendMessage(alt_text="使い方を見る", contents=carousel_contents)


@app.route("/callback", methods=['POST'])
def callback(request):
    # Check if X-Line-Signature header is present
    if 'X-Line-Signature' not in request.headers:
        app.logger.error("X-Line-Signature header not found.")
        abort(400)

    # Get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']

    # Get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # Handle webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.error("Invalid signature. Please check your channel access token/channel secret.")
        abort(400)
    except Exception as e:
        app.logger.error("An unexpected error occurred: %s", e)
        app.logger.error("Exception details: %s", traceback.format_exc())
        abort(500)

    return 'OK'


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    question = event.message.text

    if is_user_limited(user_id):
        reply_text = "1日の質問回数制限に達しました。明日またお越しください。"
        flex_message = flex_message_carousel # flexmessageのオブジェクトを変数に格納

        # 1回のreply_message()で複数のメッセージを返信
        line_bot_api.reply_message(
            event.reply_token,
            [TextSendMessage(text=reply_text), flex_message]
        )
        return

    answer_type, answer = get_answer(user_id, question)

    # Create quick reply buttons
    quick_reply_buttons = [
        QuickReplyButton(action=MessageAction(label="使い方", text="使い方")),
        QuickReplyButton(action=MessageAction(label="問題を出して", text="問題を出して")),
        QuickReplyButton(action=MessageAction(label="答えを教えて", text="答えを教えて")),
        QuickReplyButton(action=MessageAction(label="もっとわかりやすく説明をして", text="もっとわかりやすく説明をして"))
    ]
    quick_reply = QuickReply(items=quick_reply_buttons)

    if answer_type == "flex":
        line_bot_api.reply_message(
            event.reply_token,
            flex_message_carousel
        )
    elif question in template_list_a:
        line_bot_api.reply_message(
            event.reply_token,
            [
                TextSendMessage(text=answer, quick_reply=quick_reply)
            ]
        )
    else:
        response_text = f"質問：{question}\n答え：{answer}"
        line_bot_api.reply_message(
            event.reply_token,
            [
                TextSendMessage(text=response_text, quick_reply=quick_reply)
            ]
        )
        save_question_and_answer(user_id, question, answer)  

if __name__ == "__main__":
    app.run()
