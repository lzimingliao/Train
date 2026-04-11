from train_app.factory import create_app

if __name__ == "__main__":
    app = create_app()
    print("🚀 系统已启动！请在浏览器访问: http://127.0.0.1:8080")
    app.run(debug=True, port=8080)
