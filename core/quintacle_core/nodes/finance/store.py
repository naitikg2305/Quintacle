from __future__ import annotations

from pathlib import Path

import frontmatter

from ...markdown_paths import resolve_nested, safe_metadata, slugify

# Flat, not nested-per-card — unlike People (where each person's own folder
# lets a folder-scoped chat about JUST them make sense), the whole point
# here is comparing ACROSS cards ("best redemption strategy"), so every
# card's profile sits as a sibling file in the same folder. Pointing the
# existing folder-scoped chat (unchanged, see kb/chat.py) at this exact
# folder already sees every card at once — no new chat code needed.
_HOME = "Organisation/Finance/Credit Cards"


def _compose_body(
    name: str,
    issuer: str,
    annual_fee: float | None,
    rewards_summary: str,
    points_balance: float | None,
    signup_bonus: str,
    notes: str,
) -> str:
    """The folder-scoped chat (kb/chat.py's _kb_context_for_folder) reads a
    note's BODY only — frontmatter is invisible to it (same as links/asset
    fields elsewhere). Since "chat about redemption strategy" is this
    node's whole point, the structured fields have to be rendered into the
    body too, not left frontmatter-only where the chat would never see
    them. Frontmatter stays the source of truth for the page's own
    structured display (all()/get() read it directly); this is purely a
    chat-visible summary."""
    lines = [f"# {name}"]
    if issuer:
        lines.append(f"- Issuer: {issuer}")
    lines.append("- Annual fee: none" if annual_fee == 0 else f"- Annual fee: ${annual_fee:g}/year" if annual_fee is not None else None)
    if rewards_summary:
        lines.append(f"- Rewards: {rewards_summary}")
    if points_balance is not None:
        lines.append(f"- Current points balance: {points_balance:g}")
    if signup_bonus:
        lines.append(f"- Signup bonus: {signup_bonus}")
    body = "\n".join(line for line in lines if line is not None)
    return f"{body}\n\n{notes}" if notes else body


class CreditCardStore:
    """One markdown file per credit card — real structured fields (issuer,
    annual fee, rewards summary, points balance, signup bonus) plus a plain
    prose notes field, same 'structured store plus plain prose' shape as
    Documents/Home. Markdown is the source of truth; no SQLite mirror —
    nothing else holds a foreign key into a card (same reasoning as
    Wardrobe/People). Both the structured fields AND notes are kept in
    frontmatter (source of truth for the page); the body is a synthesized,
    chat-readable summary — see _compose_body()."""

    def __init__(self, kb_root: Path):
        self.kb_root = Path(kb_root)

    def _dir(self) -> Path:
        path = resolve_nested(self.kb_root, _HOME)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write(
        self,
        name: str,
        issuer: str = "",
        annual_fee: float | None = None,
        rewards_summary: str = "",
        points_balance: float | None = None,
        signup_bonus: str = "",
        notes: str = "",
    ) -> str:
        """Also serves as the update path — "I can update them myself" means
        re-saving at the same slug overwrites the existing card in place,
        same upsert-by-name convention as Document/Person."""
        slug = slugify(name)
        body = _compose_body(name, issuer, annual_fee, rewards_summary, points_balance, signup_bonus, notes)
        post = frontmatter.Post(body)
        post["name"] = name
        post["issuer"] = issuer
        post["annual_fee"] = annual_fee
        post["rewards_summary"] = rewards_summary
        post["points_balance"] = points_balance
        post["signup_bonus"] = signup_bonus
        post["notes"] = notes
        (self._dir() / f"{slug}.md").write_text(frontmatter.dumps(post), encoding="utf-8")
        return slug

    def all(self) -> list[dict]:
        results = []
        for p in sorted(self._dir().glob("*.md")):
            post = frontmatter.loads(p.read_text(encoding="utf-8"))
            metadata = safe_metadata(post, p.stem, {"issuer": "", "rewards_summary": "", "signup_bonus": "", "notes": ""})
            results.append({**metadata, "slug": p.stem})
        return results

    def get(self, name: str) -> dict | None:
        path = self._dir() / f"{slugify(name)}.md"
        if not path.exists():
            return None
        post = frontmatter.loads(path.read_text(encoding="utf-8"))
        metadata = safe_metadata(post, path.stem, {"issuer": "", "rewards_summary": "", "signup_bonus": "", "notes": ""})
        return {**metadata, "slug": path.stem}

    def delete(self, name: str) -> None:
        path = self._dir() / f"{slugify(name)}.md"
        if path.exists():
            path.unlink()


# Same folder the free-form "let's discuss stocks" chat already pushes notes
# into (seeded in kb/llm.py's SEED_FOLDERS) — a structured position sits
# right alongside that discussion, so the folder-scoped chat sees BOTH what
# you actually hold and whatever strategy notes you've saved, together.
_INVESTMENTS_HOME = "Organisation/Finance/Stocks & Investments"


def _compose_investment_body(
    name: str,
    symbol: str,
    shares: float | None,
    cost_basis: float | None,
    account: str,
    purchase_date: str | None,
    notes: str,
) -> str:
    lines = [f"# {name}"]
    if symbol:
        lines.append(f"- Ticker: {symbol}")
    if shares is not None:
        lines.append(f"- Shares: {shares:g}")
    if cost_basis is not None:
        lines.append(f"- Average cost basis: ${cost_basis:g}/share")
    if shares is not None and cost_basis is not None:
        lines.append(f"- Total invested: ${shares * cost_basis:,.2f}")
    if account:
        lines.append(f"- Account: {account}")
    if purchase_date:
        lines.append(f"- Purchase date: {purchase_date}")
    body = "\n".join(lines)
    return f"{body}\n\n{notes}" if notes else body


class InvestmentStore:
    """One markdown file per holding (a stock, ETF, fund) — a deterministic
    record of what you actually invested in: ticker, shares, cost basis,
    account, purchase date, plus free prose. No live price/market-value
    tracking (that needs an external market-data API — deliberately out of
    scope, this is a manually-updated record of your own positions, not a
    live tracker). Same structured-fields-in-frontmatter,
    chat-readable-summary-in-body shape as CreditCardStore."""

    def __init__(self, kb_root: Path):
        self.kb_root = Path(kb_root)

    def _dir(self) -> Path:
        path = resolve_nested(self.kb_root, _INVESTMENTS_HOME)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write(
        self,
        name: str,
        symbol: str = "",
        shares: float | None = None,
        cost_basis: float | None = None,
        account: str = "",
        purchase_date: str | None = None,
        notes: str = "",
    ) -> str:
        """Upsert by name — re-saving updates the same holding in place
        (e.g. adding shares and a new blended cost basis), same convention
        as every other hard node."""
        slug = slugify(name)
        body = _compose_investment_body(name, symbol, shares, cost_basis, account, purchase_date, notes)
        post = frontmatter.Post(body)
        post["name"] = name
        post["symbol"] = symbol
        post["shares"] = shares
        post["cost_basis"] = cost_basis
        post["account"] = account
        post["purchase_date"] = purchase_date
        post["notes"] = notes
        (self._dir() / f"{slug}.md").write_text(frontmatter.dumps(post), encoding="utf-8")
        return slug

    def all(self) -> list[dict]:
        results = []
        for p in sorted(self._dir().glob("*.md")):
            post = frontmatter.loads(p.read_text(encoding="utf-8"))
            metadata = safe_metadata(post, p.stem, {"symbol": "", "account": "", "notes": ""})
            results.append({**metadata, "slug": p.stem})
        return results

    def get(self, name: str) -> dict | None:
        path = self._dir() / f"{slugify(name)}.md"
        if not path.exists():
            return None
        post = frontmatter.loads(path.read_text(encoding="utf-8"))
        metadata = safe_metadata(post, path.stem, {"symbol": "", "account": "", "notes": ""})
        return {**metadata, "slug": path.stem}

    def delete(self, name: str) -> None:
        path = self._dir() / f"{slugify(name)}.md"
        if path.exists():
            path.unlink()
