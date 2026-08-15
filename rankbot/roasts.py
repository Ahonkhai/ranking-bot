"""Replies for members who aren't on the board.

Short and blunt on purpose — the joke is the whole point, so no explanation
and no emoji.

"Unranked" means no ledger entry at all, which is what `cards.build()` returns
None for. Someone legitimately sitting on $0 has an entry and is ranked, so
they get their card like anyone else.
"""

import random

# Second person: the sender asking about themselves.
SELF_RESPONSES = (
    "sorry you are pissy poor",
    "zero licks",
    "you have no rank",
    "Rank: pooron",
    "you're not on the leaderboard",
)

# Third person: `{name}` is the target's @handle, or their display name when
# they have no username.
OTHER_RESPONSES = (
    "{name} has zero licks",
    "{name} is pissy poor",
    "{name} has no rank",
    "{name} is a pooron",
    "{name} isn't on the leaderboard",
)


def get_unranked_self_response() -> str:
    return random.choice(SELF_RESPONSES)


def get_unranked_user_response(name: str) -> str:
    return random.choice(OTHER_RESPONSES).format(name=name)
