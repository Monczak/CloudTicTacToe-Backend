import asyncio
import json
import os
import random
from typing import List, Dict
from functools import wraps
from io import BytesIO
import boto3
import botocore
import boto3.exceptions
import botocore.errorfactory
import botocore.exceptions
import aioboto3
from quart import Quart, websocket, request, jsonify, send_file
from quart_sqlalchemy import SQLAlchemyConfig
from quart_sqlalchemy.framework import QuartSQLAlchemy
from sqlalchemy import Identity, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
import requests

from game.tictactoe import Player, TicTacToeGame, MoveResult

REGION = "us-east-1"
AVATAR_BUCKET = "cloudtictactoe-avatars"

app = Quart(__name__)

db = QuartSQLAlchemy(
    config=SQLAlchemyConfig(
        binds=dict(
            default=dict(
                engine=dict(
                    url=f"mysql+pymysql://{os.environ['DB_USERNAME']}:{os.environ['DB_PASSWORD']}@{os.environ['DB_ENDPOINT']}/main",
                    echo=True,
                ),
                session=dict(
                    expire_on_commit=False,
                )
            )
        )
    ),
    app=app,
)

cognito = boto3.client("cognito-idp", region_name=REGION)
s3 = boto3.client("s3", region_name=REGION, 
                  aws_access_key_id=os.environ["aws_access_key_id"], 
                  aws_secret_access_key=os.environ["aws_secret_access_key"],
                  aws_session_token=os.environ["aws_session_token"])

matchmaking_queue = set()
connected = set()

client_id = os.environ["COGNITO_CLIENT_ID"]


class TicTacToeGameResult(db.Model):
    __tablename__ = "tic_tac_toe_game_result"
    id: Mapped[int] = mapped_column(Identity(), primary_key=True, autoincrement=True)
    player_o: Mapped[str] = mapped_column(String(32))
    player_x: Mapped[str] = mapped_column(String(32))
    result: Mapped[str] = mapped_column(String(10))


class TicTacToeGameWrapper:
    def __init__(self, player_o_websocket, player_o_name, player_x_websocket, player_x_name) -> None:
        self.game_data = TicTacToeGame()
        self.player_o = player_o_websocket
        self.player_x = player_x_websocket
        self.player_o_name = player_o_name
        self.player_x_name = player_x_name

    def is_player_turn(self, ctx) -> bool:
        player = self.get_player(ctx)
        if player is None:
            return False
        
        if player == self.game_data.current_player:
            return True
        
        return False
    
    def get_player(self, ctx) -> Player | None:
        if ctx == self.player_o:
            return Player.O
        if ctx == self.player_x:
            return Player.X
        return None


games = {}
player_data = {}


def collect_websocket(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        websocket_obj = websocket._get_current_object()
        connected.add(websocket_obj)
        try:
            return await func(websocket_obj, *args, **kwargs)
        finally:
            connected.remove(websocket_obj)
    return wrapper


@app.route("/")
async def index():
    return "Hello World!"


@app.route("/auth/get_user", methods=["GET"])
async def auth_get_user():
    bearer = request.headers.get("Authorization")
    if bearer is None:
        return jsonify({"intent":"error", "description":"No auth token specified"}), 401

    access_token = bearer.split()[1]
    user_data = get_user_data(access_token)
    if user_data is None:
        return jsonify({"intent":"error", "description": "Unauthorized"}), 401

    return jsonify({"intent":"success", **user_data})


@app.route("/upload-avatar", methods=["POST"])
async def upload_avatar():
    request_files = await request.files
    username = request.args.get("username")

    if username is None:
        return {"intent": "error", "description": "Username needs to be specified"}, 400

    if "avatar" in request_files:
        avatar_file = request_files["avatar"]
        file_key = username

        s3.upload_fileobj(avatar_file, AVATAR_BUCKET, file_key)
    
    return {"intent": "success"}


@app.route("/get-avatar", methods=["GET"])
async def get_avatar():
    username = request.args.get("username")
    if username is None:
        return {"intent": "error", "description": "Username needs to be specified"}, 400
    
    url = f"https://{AVATAR_BUCKET}.s3.amazonaws.com/{username}"
    response = requests.get(url)
    if response.status_code == 200:
        return jsonify({"intent": "success", "url": url})
        
    return jsonify({"intent": "error", "description": "No avatar found for this user"})


@app.route("/auth", methods=["GET", "POST"])
async def auth():
    request_json = await request.json
    match action := request.args.get("action"):
        case "signup":
            try:
                response = cognito.sign_up(
                    ClientId=client_id,
                    Username=request_json["username"],
                    Password=request_json["password"],
                    UserAttributes=[
                        {
                            "Name": "email",
                            "Value": request_json["email"]
                        }
                    ]
                )

                return jsonify({"intent":"awaiting_verification"}), 200
            except botocore.exceptions.ClientError as e: 
                match e.response["Error"]["Code"]:
                    case "InvalidParameterException":
                        return jsonify({"intent":"error","description":"Invalid email, username or password"}), 400
                    case "UserExistsException":
                        return jsonify({"intent":"error","description":"This user already exists"}), 400
                    case "UsernameExistsException":
                        return jsonify({"intent":"error","description":"A user with this username already exists. Pick a different username"}), 400
                    case _:
                        return jsonify({"intent":"error","description":e.response["Error"]["Message"]}), 400
            except Exception as e:
                return jsonify({"intent":"error","description":str(e)}), 400
                        

        case "login" | "refresh":
            try:
                response = cognito.initiate_auth(
                    ClientId=client_id,
                    AuthFlow="USER_PASSWORD_AUTH" if action == "login" else "REFRESH_TOKEN",
                    AuthParameters={
                        "USERNAME":request_json["username"],
                        "PASSWORD":request_json["password"]
                    } if action == "login" else {
                        "REFRESH_TOKEN": request_json["refresh_token"]
                    }
                )
                return jsonify({
                    "intent":"success", 
                    "access_token": response["AuthenticationResult"]["AccessToken"],
                    "refresh_token": response["AuthenticationResult"]["RefreshToken"],
                    "token_type": response["AuthenticationResult"]["TokenType"],
                    "expires_in": response["AuthenticationResult"]["ExpiresIn"]
                    }), 200
            except botocore.exceptions.ClientError as e: 
                match e.response["Error"]["Code"]:
                    case "NotAuthorizedException":
                        return jsonify({"intent":"error","description":"Invalid username or password"}), 400
                    case "UserNotConfirmedException":
                        return jsonify({"intent":"error","description":"User not confirmed"}), 400
                    case _:
                        return jsonify({"intent":"error","description":e.response["Error"]["Message"]}), 400

            except Exception as e:
                return jsonify({"intent":"error","description":str(e)}), 400

        case "verify":
            try:
                response = cognito.confirm_sign_up(
                    ClientId=client_id,
                    Username=request_json["username"],
                    ConfirmationCode=request_json["code"]
                )
                return jsonify({"intent":"success"}), 200
            except botocore.exceptions.ClientError as e: 
                match e.response["Error"]["Code"]:
                    case "CodeMismatchException" | "ExpiredCodeException":
                        return jsonify({"intent":"error","description":"Wrong verification code"}), 400
                    case _:
                        return jsonify({"intent":"error","description":e.response["Error"]["Message"]}), 400
            except Exception as e:
                return jsonify({"intent":"error","description":str(e)}), 400

        case "logout":
            try:
                bearer = request.headers.get("Authorization")
                response = cognito.global_sign_out(
                    AccessToken=bearer.split()[1]
                )
                return jsonify({"intent":"success", }), 200
            except botocore.exceptions.ClientError as e: 
                match e.response["Error"]["Code"]:
                    case "NotAuthorizedException":
                        return jsonify({"intent":"error","description":"Token revoked"}), 401
                    case _:
                        return jsonify({"intent":"error","description":e.response["Error"]["Message"]}), 400
            except Exception as e:
                return jsonify({"intent":"error","description":str(e)}), 400

        case _:
            return jsonify({"intent":"error","description":"Invalid auth action"}), 400


def get_user_data(token):
    try:
        response = cognito.get_user(AccessToken=token)
        attributes = response["UserAttributes"]
        data = {
            "username": response["Username"],
            "email": [a for a in attributes if a["Name"] == "email"][0]["Value"],
            "email_verified": [a for a in attributes if a["Name"] == "email_verified"][0]["Value"],
            "sub": [a for a in attributes if a["Name"] == "sub"][0]["Value"],
        }
        return data
    except botocore.exceptions.ClientError as e:
        match e.response["Error"]["Code"]:
            case "NotAuthorizedException" | "UserNotFoundException":
                return None
            case _:
                return jsonify({"intent":"error","description":e.response["Error"]["Message"]}), 400


def store_result(player_o, player_x, result):
    db.create_all()

    with db.bind.Session() as s:
        with s.begin():
            result = TicTacToeGameResult(player_o=player_o, player_x=player_x, result=result)
            s.add(result)
            s.flush()
            s.refresh(result)


async def handle_message(ctx, message):
    token = message.get("token")

    match message["intent"]:
        case "pingpong":
            await ctx.send_json({"intent": "pingpong"})

        case "join_match":
            user_data = get_user_data(token)
            if user_data is None:
                raise ValueError("Unauthorized")

            if ctx in matchmaking_queue:
                raise ValueError("Already in matchmaking queue")
            
            if ctx in games:
                raise ValueError("Already in a game")

            player_data[ctx] = user_data["username"]
            matchmaking_queue.add(ctx)
            await ctx.send_json({"intent": "info", "description": "Joined matchmaking queue"})

            if len(matchmaking_queue) >= 2:
                player1, player2 = random.sample(list(matchmaking_queue), 2)
                matchmaking_queue.remove(player1)
                matchmaking_queue.remove(player2)

                game = TicTacToeGameWrapper(player1, player_data[player1], player2, player_data[player2])
                games[player1] = game
                games[player2] = game

                await player1.send_json({"intent": "game_start", "player": Player.O.value, "opponentName": game.player_x_name})
                await player2.send_json({"intent": "game_start", "player": Player.X.value, "opponentName": game.player_o_name})  
           
        case "make_move":
            if get_user_data(token) is None:
                raise ValueError("Unauthorized")

            if ctx not in games:
                raise ValueError("Not in a game")
            
            game = games[ctx]

            if not game.is_player_turn(ctx):
                raise ValueError("Not your turn")
            
            result = game.game_data.make_move(message["cellIdx"])
            if result == MoveResult.INVALID:
                raise ValueError("Illegal move")

            response = {
                "intent": "move_result", 
                "player": game.get_player(ctx).value, 
                "moveResult": result.value, 
                "boardState": list(map(lambda player: player.value, game.game_data.board)), 
                "newestMove": message["cellIdx"]
            }
            await game.player_o.send_json(response)
            await game.player_x.send_json(response)

            if result in (MoveResult.WIN_O, MoveResult.WIN_X, MoveResult.DRAW):
                games.pop(game.player_o)
                games.pop(game.player_x)
                player_data.pop(game.player_o)
                player_data.pop(game.player_x)
                store_result(game.player_o_name, game.player_x_name, str(result))

        case _:
            raise ValueError("Invalid intent")


@app.websocket("/ws")
@collect_websocket
async def ws(ctx):
    while True:
        try:
            message = await ctx.receive_json()
            await handle_message(ctx, message)
        except json.JSONDecodeError:
            await ctx.send_json({"intent": "error", "description": "Invalid JSON"})
        except asyncio.CancelledError as e:
            if ctx in matchmaking_queue:
                matchmaking_queue.remove(ctx)

            if ctx in games:
                game = games[ctx]

                store_result(game.player_o_name, game.player_x_name, "disconnect")

                games.pop(game.player_o)
                games.pop(game.player_x)
                player_data.pop(game.player_o)
                player_data.pop(game.player_x)

                opponent = game.player_o if ctx == game.player_x else game.player_x
                await opponent.send_json({"intent": "error", "description": "Opponent disconnected"})
                
            raise e
        except Exception as e:
            await ctx.send_json({"intent": "error", "description": str(e)})


def main():
    app.run(debug=True, ssl_context=("cert.pem", "key.pem"))


if __name__ == "__main__":
    main()
