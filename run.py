from app import create_app

app = create_app()


if __name__ == "__main__":
    app.run(host=app.config["AX_HOST"], port=app.config["AX_PORT"], debug=False)
