import enum
from typing import List


class Player(enum.Enum):
    NONE = " "
    O = "O"
    X = "X"


class MoveResult(enum.Enum):
    NONE = "none",
    INVALID = "invalid",
    WIN_O = "winO",
    WIN_X = "winX",
    DRAW = "draw"


class TicTacToeGame:
    def __init__(self, starting_player: Player = None) -> None:
        self.board: List[Player] = [Player.NONE] * 9
        self.current_player: Player = Player.O if starting_player is None else starting_player
    
    def make_move(self, cell_idx: int, player: Player = None) -> MoveResult:
        player = self.current_player if player is None else player
        check_result = self._check_move(player, cell_idx)
        if check_result == MoveResult.INVALID:
            return check_result

        self.board[cell_idx] = player
        self.current_player = Player.X if self.current_player == Player.O else Player.O
        
        return self._check_win()
    
    def _check_move(self, player: Player, cell_idx: int) -> MoveResult:
        if self.board[cell_idx] != Player.NONE:
            return MoveResult.INVALID

    
    def _check_win(self) -> MoveResult:        
        win_check_axes = (
            (0, 1, 2),
            (3, 4, 5),
            (6, 7, 8),
            (0, 3, 6),
            (1, 4, 7),
            (2, 5, 8),
            (0, 4, 8),
            (2, 4, 6)
        )

        for axis in win_check_axes:
            players = list(map(lambda i: self.board[i], axis))
            if players[0] == players[1] == players[2] and players[0] != Player.NONE:
                return MoveResult.WIN_O if players[0] == Player.O else MoveResult.WIN_X
            
        if Player.NONE not in self.board:
            return MoveResult.DRAW
        
        return MoveResult.NONE


if __name__ == "__main__":
    game = TicTacToeGame()
    moves = (0, 4, 1, 5, 2)

    for move in moves:
        result = game.make_move(game.current_player, move)
        for i, player in enumerate(game.board):
            print(player.value, end="")
            if i % 3 == 2:
                print()
        
        print(result)
    