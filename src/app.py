from quart import Quart

app = Quart(__name__)


@app.route("/")
async def index():
    return "Hello World!"


def main():
    app.run(debug=True)


if __name__ == "__main__":
    main()
