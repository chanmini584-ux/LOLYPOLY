"""누가 무엇을 할 수 있는지(서버에서 판정). 화면의 버튼 숨김과 별개로 모든 변경 요청이 여기를 거친다.

B2 규칙
- 읽기: 로그인한 정상 계정은 전체 게시판과 모든 학과 게시판을 읽는다.
- 쓰기(새 글·댓글·답글): 전체 게시판은 누구나, 학과 게시판은 '지금' 그 학과 소속만.
- 공감·스크랩·신고·차단: 읽을 수 있는 글이면 다른 과도 가능.
- 수정·삭제: 본인 글·댓글만. 학과를 옮긴 뒤에도 예전에 쓴 본인 글은 수정·삭제할 수 있다
  (옮기기 전 학과 게시판에 새 글·댓글을 쓰는 것은 안 된다). 이용 제한 중에는 수정은 안 되고 삭제만 된다.
"""

from .models import Board, Comment, Post

MODERATE_PERM = "community.moderate"


def is_moderator(user) -> bool:
    return user.is_authenticated and user.is_active and user.has_perm(MODERATE_PERM)


def write_block_reason(user, board: Board) -> str:
    """이 게시판에 새 글·댓글을 쓸 수 없는 이유. 쓸 수 있으면 빈 문자열."""
    if user.is_restricted:
        return f"이용 제한 중이라 {user.restricted_until:%m월 %d일 %H:%M}까지 글·댓글을 쓸 수 없어요."
    if board.is_all:
        return ""
    if not board.department.is_active:
        return "지금은 운영하지 않는 학과 게시판이라 읽기만 할 수 있어요."
    if user.department_id != board.department_id:
        return f"읽기만 할 수 있어요. 글·댓글은 {board.department.name} 소속만 쓸 수 있어요."
    return ""


def can_write(user, board: Board) -> bool:
    return not write_block_reason(user, board)


def can_edit_post(user, post: Post) -> bool:
    return post.author_id == user.id and post.status == Post.VISIBLE and not user.is_restricted


def can_delete_post(user, post: Post) -> bool:
    return post.author_id == user.id and post.status != Post.DELETED


def can_delete_comment(user, comment: Comment) -> bool:
    return comment.author_id == user.id and comment.status != Comment.DELETED
