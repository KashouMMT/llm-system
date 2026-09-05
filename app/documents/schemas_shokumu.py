from itertools import pairwise

from pydantic import BaseModel, Field, field_validator, model_validator

from app.documents.schemas_rirekisho import KANA_PATTERN, YearMonth


class JobEntry(BaseModel):
    """
    One employer's entry in 職務経歴.

    Deliberately one flexible shape rather than several rigid ones: the
    reference 職務経歴書 this was built against has two job entries with
    different internal structure — one uses a side table of technologies
    and team size next to a single project description, the other is plain
    paragraphs with no side table at all. Every content field here is
    optional so either shape (and everything in between) fits without
    forcing a project sub-table onto a job that never had one.
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
    employment_type: str | None = Field(
        default=None,
        max_length=50,
        description="雇用形態, e.g. '正社員', '契約社員'.",
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
        description="業務概要・プロジェクト概要, in the user's own words.",
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
    technologies: list[str] = Field(
        default_factory=list,
        description="使用技術・開発環境, e.g. ['Java', 'Android', 'iOS'].",
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
            "date. Only include wording the user has seen and approved."
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
    applicable_skills: list[str] = Field(
        default_factory=list,
        description="活かせる経験・知識・技術: one bullet per item.",
    )
    self_pr_heading: str | None = Field(
        default=None,
        max_length=200,
        description=(
            "自己PR's short bold headline, e.g. '＜変化の多い現場でも、仕様"
            "を正しく理解し開発を前に進める力＞'. Leave empty if the user "
            "does not want one."
        ),
    )
    self_pr: str | None = Field(
        default=None,
        max_length=1500,
        description=(
            "自己PR body. Only include wording the user has seen and "
            "approved — never write this on their behalf without showing "
            "it first."
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
