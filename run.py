"""
程式進入點。

開發：  flask run            （讀 .flaskenv 裡的 FLASK_APP=run.py）
或：    python run.py
正式：  gunicorn "run:app"   （Linux）  /  waitress-serve run:app（Windows）
"""
from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
