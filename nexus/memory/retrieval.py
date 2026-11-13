import re

from sqlalchemy import select

from nexus.db.models import Knowledge


async def retrieve(session, workspace_id: str, project_id: str, query: str) -> list[dict]:
    rows = (
        await session.scalars(
            select(Knowledge)
            .where(Knowledge.workspace_id == workspace_id, Knowledge.project_id == project_id)
            .order_by(Knowledge.version.desc())
            .limit(200)
        )
    ).all()
    # Retain latest approved version per title; suggestions cannot overwrite an approval.
    latest = {}
    for row in sorted(rows, key=lambda r: (r.approved, r.version), reverse=True):
        latest.setdefault(row.title, row)
    terms = set(re.findall(r"\w+", query.lower()))
    ranked = sorted(
        latest.values(),
        key=lambda r: (
            r.approved,
            len(terms & set(re.findall(r"\w+", (r.title + " " + r.content).lower()))),
        ),
        reverse=True,
    )
    result, remaining = [], 12000
    for row in ranked[:8]:
        if remaining <= 0:
            break
        text = row.content[:remaining]
        remaining -= len(text)
        result.append(
            {
                "id": row.id,
                "title": row.title,
                "content": text,
                "source": row.source,
                "version": row.version,
                "approved": row.approved,
                "truncated": len(text) < len(row.content),
            }
        )
    return result
