import asyncio
import json
import random
from typing import List, Dict
from functools import wraps
from quart import Quart, websocket

from game.tictactoe import Player, TicTacToeGame, MoveResult

app = Quart(__name__)

matchmaking_queue = set()
connected = set()


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
        global connected
        connected.add(websocket._get_current_object())
        try:
            return await func(websocket._get_current_object(), *args, **kwargs)
        finally:
            connected.remove(websocket._get_current_object())
    return wrapper


@app.route("/")
async def index():
    return "Hello World!"


async def handle_message(ctx, message):
    match message["intent"]:
        case "pingpong":
            await ctx.send_json({"intent": "pingpong"})

        case "join_match":
            if ctx in matchmaking_queue:
                raise ValueError("Already in matchmaking queue")
            
            if ctx in games:
                raise ValueError("Already in a game")

            player_data[ctx] = message["playerName"]
            matchmaking_queue.add(ctx)
            await ctx.send_json({"intent": "info", "description": "Joined matchmaking queue"})

            if len(matchmaking_queue) >= 2:
                player1, player2 = random.sample(list(matchmaking_queue), 2)
                matchmaking_queue.remove(player1)
                matchmaking_queue.remove(player2)

                game = TicTacToeGameWrapper(player1, player_data[player1], player2, player_data[player2])
                games[player1] = game
                games[player2] = game

                await player1.send_json({"intent": "game_start", "player": "o", "opponentName": game.player_x_name})
                await player2.send_json({"intent": "game_start", "player": "x", "opponentName": game.player_o_name})  
           
        case "make_move":
            if ctx not in games:
                raise ValueError("Not in a game")
            
            game = games[ctx]

            if not game.is_player_turn(ctx):
                raise ValueError("Not your turn")
            
            result = game.game_data.make_move(message["cellIdx"])
            if result == MoveResult.INVALID:
                raise ValueError("Illegal move")

            response = {"intent": "move_result", "player": game.get_player(ctx).value, "moveResult": result.value, "boardState": list(map(lambda player: player.value, game.game_data.board))}
            await game.player_o.send_json(response)
            await game.player_x.send_json(response)

            if result in (MoveResult.WIN_O, MoveResult.WIN_X):
                games.pop(game.player_o)
                games.pop(game.player_x)
                player_data.pop(game.player_o)
                player_data.pop(game.player_x)

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
    app.run(debug=True)


if __name__ == "__main__":
    main()
