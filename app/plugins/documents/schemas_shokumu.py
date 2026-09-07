from itertools import pairwise

from pydantic import BaseModel, Field, field_validator, model_validator

from app.plugins.documents.schemas_rirekisho import (
    KANA_PATTERN,
    LicenseEntry,
    YearMonth,
)


class TechGroup(BaseModel):
    """
    One labelled group of technologies, e.g. 【言語】Java.

    Grouped rather than a flat list because the reference 職務経歴書 prints
    them under headings — 言語, OS, DB, ツール — and a single undifferentiated
    run of names reads as a keyword dump to a Japanese reviewer.
    """

    category: str = Field(
        min_length=1,
        max_length=30,
        description=(
            "The group heading without brackets, e.g. '言語', 'OS', 'DB', "
            "'フレームワーク', '開発環境'. The renderer adds the 【】."
        ),
    )
    items: list[str] = Field(
        min_length=1,
        description="Names in this group, e.g. ['Java', 'Kotlin'].",
    )


class PcSkill(BaseModel):
    """One row of ■PCスキル."""

    tool: str = Field(
        min_length=1,
        max_length=50,
        description="Software name, e.g. 'Word', 'Excel', 'PowerPoint'.",
    )
    level: str = Field(
        min_length=1,
        max_length=200,
        description=(
            "What the user can actually do with it, in their own words, e.g. "
            "'入力、四則演算、SUM、vlookup関数などの使用が可能なレベル'. Never "
            "invent a level — ask what they can do rather than guessing from "
            "the job title."
        ),
    )


class SelfPrBlock(BaseModel):
    """
    One ＜見出し＞ plus its paragraphs in ■自己PR.

    A list rather than a single block because two of the four reference
    documents make two separate points under 自己PR, each with its own
    heading. Collapsing them into one field forced the earlier version to
    either drop a heading or bury it inside the body text.
    """

    heading: str | None = Field(
        default=None,
        max_length=200,
        description=(
            "Short headline for this point, conventionally in ＜＞, e.g. "
            "'＜相手の気持ちを汲み取り臨機応変に対応する力＞'. Leave empty if "
            "the user does not want one."
        ),
    )
    body: str = Field(
        min_length=1,
        max_length=1500,
        description=(
            "The paragraphs supporting this point. Use newlines between "
            "paragraphs. Only include wording the user has seen and "
            "approved — never write this on their behalf without showing it "
            "first."
        ),
    )


class JobEntry(BaseModel):
    """
    One employer's entry in 職務経歴.

    Deliberately one flexible shape rather than several rigid ones: the
    four reference 職務経歴書 this was built against differ in which fields
    they use — one carries a side table of technologies and team size, one
    leads with 事業内容 and 資本金, one is plain paragraphs. Every content
    field here is optional so any of those shapes fits without forcing a
    section onto a job that never had one.
    """

    company: str = Field(
        min_length=1,
        max_length=100,
        description="会社名, copied exactly as the user gives it.",
    )
    start: YearMonth = Field(description="入社/着任 年月.")
    end: YearMonth | None = Field(
        default=None,
        description=(
            "退職/契約終了 年月. Leave empty if the user is still there — "
            "the renderer writes 現在."
        ),
    )
    assignment: str | None = Field(
        default=None,
        max_length=200,
        description=(
            "常駐先・配属先, e.g. '〇〇株式会社にて常駐開発'. Only for "
            "dispatch/secondment work — leave empty otherwise."
        ),
    )
    business_description: str | None = Field(
        default=None,
        max_length=200,
        description=(
            "事業内容: what the employer does, e.g. '医療クリニック（美容外科・"
            "形成外科）'. Worth asking for — a reviewer who does not know the "
            "company reads this first. Leave empty if the user does not know."
        ),
    )
    capital: str | None = Field(
        default=None,
        max_length=50,
        description=(
            "資本金 as written, including the unit, e.g. '500万円'. Leave "
            "empty unless the user states it — never look it up or estimate."
        ),
    )
    employee_count: str | None = Field(
        default=None,
        max_length=50,
        description=(
            "従業員数 as written, e.g. '約50名', '470人（2024年12月現在）'. "
            "Leave empty unless the user states it."
        ),
    )
    employment_type: str | None = Field(
        default=None,
        max_length=50,
        description="雇用形態, e.g. '正社員', '契約社員', '派遣社員'.",
    )
    title: str | None = Field(
        default=None,
        max_length=200,
        description=(
            "A short line naming the role or what was built, e.g. "
            "'家庭用エネルギーシステム向けスマホ操作アプリ開発'. Leave "
            "empty if the user did not give one."
        ),
    )
    overview: str | None = Field(
        default=None,
        max_length=1000,
        description=(
            "業務概要・プロジェクト概要, in the user's own words. Use "
            "newlines between paragraphs."
        ),
    )
    phase: str | None = Field(
        default=None,
        max_length=200,
        description="担当フェーズ, e.g. '設計、開発、テスト'.",
    )
    responsibilities: list[str] = Field(
        default_factory=list,
        description=(
            "業務内容・担当業務: one bullet per concrete task. Never "
            "invent a task the user did not describe."
        ),
    )
    achievements: list[str] = Field(
        default_factory=list,
        description=(
            "実績・取り組み: one bullet per concrete outcome or initiative. "
            "Leave empty if the user has none to state — do not invent a "
            "number or result they never gave."
        ),
    )
    technologies: list[TechGroup] = Field(
        default_factory=list,
        description=(
            "使用技術・開発環境, grouped by kind, e.g. "
            "[{category: '言語', items: ['Java']}, "
            "{category: 'OS', items: ['Android', 'iOS']}]. Leave empty for "
            "a job with no technical stack to list."
        ),
    )
    team_size: str | None = Field(
        default=None,
        max_length=100,
        description=(
            "規模・配属部署の規模: team size and/or the user's role in it, "
            "e.g. '全10名、設計・テスト担当'."
        ),
    )


class ShokumuKeirekisho(BaseModel):
    """
    A 職務経歴書, complete or partial.

    Jobs are newest first — the opposite convention from 履歴書's 学歴・
    職歴, which is oldest first. Worth stating explicitly rather than
    assuming the model transfers the other document's convention here.

    Unlike 履歴書, this document has no fixed form: it flows onto as many
    pages as it needs, so nothing here is constrained by how much room a
    printed box has. Every section is optional and simply does not render
    when empty — a user with no certifications gets no ■資格 heading at
    all, rather than a heading over an empty table.
    """

    name: str = Field(
        min_length=1,
        max_length=50,
        description="Full name in kanji, family name first, e.g. '山田 太郎'.",
    )
    name_kana: str = Field(
        default="",
        max_length=50,
        description=(
            "Reading of the name, kana only — no kanji, no romaji. A "
            "non-Japanese name takes katakana ('ジャン・デュポン'), which is "
            "how a Japanese reader is expected to pronounce it, and is "
            "worth asking for whenever the name is not already in kanji. "
            "Rendered beside the name as 氏名　Jean Dupont（ジャン・デュポン）. "
            "Leave empty if the user does not know it or does not want one."
        ),
    )
    summary: str | None = Field(
        default=None,
        max_length=1000,
        description=(
            "職務要約: a short paragraph summarizing the whole career to "
            "date. Use newlines between paragraphs. Only include wording "
            "the user has seen and approved."
        ),
    )
    jobs: list[JobEntry] = Field(
        default_factory=list,
        description=(
            "職務経歴, newest employer first. You MUST ask about work "
            "history before generating — leave empty only if the user has "
            "no work history at all."
        ),
    )
    pc_skills: list[PcSkill] = Field(
        default_factory=list,
        description=(
            "■PCスキル: which software the user can operate and to what "
            "level. Worth asking about for office and administrative roles, "
            "where it is conventional. Leave empty if the user has nothing "
            "to state — the section is then omitted entirely."
        ),
    )
    licenses: list[LicenseEntry] = Field(
        default_factory=list,
        description=(
            "■資格, oldest first. Same rules as the 履歴書's 免許・資格, "
            "including the 合格 / 取得 suffix. Unlike the 履歴書 form there "
            "is no row limit here, so list everything relevant. Leave empty "
            "if the user holds none."
        ),
    )
    applicable_skills: list[str] = Field(
        default_factory=list,
        description="活かせる経験・知識・技術: one bullet per item.",
    )
    self_pr_blocks: list[SelfPrBlock] = Field(
        default_factory=list,
        description=(
            "■自己PR, one entry per distinct strength being argued. Most "
            "documents have one or two. Only include wording the user has "
            "seen and approved — never write this on their behalf without "
            "showing it first."
        ),
    )

    @field_validator("name_kana")
    @classmethod
    def _name_kana_only(cls, value: str) -> str:
        # Blank means the user chose not to supply it, which is not an
        # error — only a value that is present and malformed is. Same rule
        # as 履歴書's furigana, deliberately sharing that pattern so one
        # name cannot pass on one document and fail on the other.
        if not value:
            return value

        if not KANA_PATTERN.match(value):
            raise ValueError(f"must be kana only (hiragana or katakana); got {value!r}")

        return value

    @model_validator(mode="after")
    def _jobs_newest_first(self) -> "ShokumuKeirekisho":
        for later, earlier in pairwise(self.jobs):
            if later.start.as_tuple() < earlier.start.as_tuple():
                raise ValueError(
                    "jobs must be newest first: "
                    f"'{later.company}' ({later.start}) appears after "
                    f"'{earlier.company}' ({earlier.start})."
                )

        return self

    @classmethod
    def blank(cls) -> "ShokumuKeirekisho":
        """
        An all-empty instance, for rendering a printable form to fill in
        by hand. See Rirekisho.blank — same reasoning: `model_construct`
        because a blank form has no name, and every other field already
        defaults to empty and is skipped by the renderer when so.
        """
        return cls.model_construct(name="")
