"""
Renders a 職務経歴書 into the .docx template.

Unlike the 履歴書 form, this document flows: it paginates itself, so there
is no slot map, no capacity budget, and no overflow to raise. What the
renderer does instead is flatten each section into a list of lines, so the
template can loop over them with a single tag rather than carrying three
docxtpl paragraphs for every optional field. All the branching that decides
what a section says therefore lives here, in plain Python, where it can be
read and tested without opening Word.
"""

from io import BytesIO
from pathlib import Path

from docxtpl import DocxTemplate

from app.plugins.documents.schemas_shokumu import JobEntry, ShokumuKeirekisho
from app.utils.jst import today_in_japan

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


class DocxRenderer:
    """
    Renders a 職務経歴書 to .docx by filling the template.

    Implements the Renderer protocol. The template carries the page setup,
    fonts, footers, and table ruling from the client-approved reference; a
    styling change is an edit in Word, not a code change.
    """

    extension = "docx"
    content_type = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

    def __init__(
        self, template_name: str = "shokumu_keirekisho.docx", *, dated: bool = True
    ) -> None:
        self._template_path = TEMPLATES_DIR / template_name
        # See XlsxRenderer._dated: a blank form carries no generation date.
        self._dated = dated

    def render(self, data: ShokumuKeirekisho) -> bytes:
        template = DocxTemplate(self._template_path)
        template.render(_context(data, dated=self._dated))

        buffer = BytesIO()
        template.save(buffer)

        return buffer.getvalue()


def _paragraphs(text: str | None) -> list[str]:
    """
    Split free text into the paragraphs it should render as.

    Blank lines are dropped rather than preserved: they are how a person
    separates paragraphs when typing into a chat box, and the template
    already puts vertical space between paragraphs.
    """
    if not text:
        return []

    return [line.strip() for line in text.splitlines() if line.strip()]


def _context(data: ShokumuKeirekisho, *, dated: bool = True) -> dict:
    name_line = data.name

    if data.name_kana:
        name_line = f"{data.name}（{data.name_kana}）"

    return {
        # The whole right-aligned date line, not just the year: the
        # template run is "{{ generated_on_line }}" so a blank form renders
        # an empty line rather than a stray "年現在".
        "generated_on_line": f"{today_in_japan().year}年現在" if dated else "",
        "name_line": name_line,
        "summary_lines": _paragraphs(data.summary),
        "jobs": [
            {
                "number": number,
                "header": _job_header(job),
                "lines": _job_lines(job),
            }
            for number, job in enumerate(data.jobs, start=1)
        ],
        "pc_skills": [
            {"tool": skill.tool, "level": skill.level} for skill in data.pc_skills
        ],
        "licenses": [
            {"period": str(entry.period), "name": entry.name} for entry in data.licenses
        ],
        "applicable_skills": list(data.applicable_skills),
        "self_pr_lines": _self_pr_lines(data),
    }


def _job_header(job: JobEntry) -> str:
    """The shaded row: when, where, and on whose site."""
    # An employer the user has not left has no end date, and inventing one
    # would put a resignation on the document that never happened.
    end = str(job.end) if job.end else "現在"

    header = f"{job.start}～{end}　　{job.company}"

    if job.assignment:
        header = f"{header}（{job.assignment}）"

    return header


def _job_lines(job: JobEntry) -> list[str]:
    """
    Every line inside one job's body cell, in reading order.

    The order follows the reference documents: who the employer is, then
    what the role was, then what was actually done, then the outcomes, and
    the technical detail last. Each block is skipped entirely when its
    field is empty, so a job with no achievements shows no 【実績・取り組み】
    heading rather than an empty one.
    """
    lines: list[str] = []

    if job.business_description:
        lines.append(f"事業内容：{job.business_description}")

    # 資本金 and 従業員数 share a line, as in the reference documents, but
    # only the parts that were actually given.
    company_facts = [
        label + value
        for label, value in (
            ("資本金：", job.capital),
            ("従業員数：", job.employee_count),
        )
        if value
    ]

    if company_facts:
        lines.append("　".join(company_facts))

    if job.employment_type:
        lines.append(f"【雇用形態】{job.employment_type}")

    if job.title:
        lines.append(job.title)

    if job.overview:
        lines.append("【業務概要】")
        lines.extend(_paragraphs(job.overview))

    if job.phase:
        lines.append(f"【担当フェーズ】{job.phase}")

    if job.responsibilities:
        lines.append("【業務内容】")
        lines.extend(f"・{item}" for item in job.responsibilities)

    if job.achievements:
        lines.append("【実績・取り組み】")
        lines.extend(f"・{item}" for item in job.achievements)

    if job.technologies:
        lines.append("【使用技術】")
        lines.extend(
            f"　{group.category}：{'、'.join(group.items)}"
            for group in job.technologies
        )

    if job.team_size:
        lines.append(f"【規模】{job.team_size}")

    return lines


def _self_pr_lines(data: ShokumuKeirekisho) -> list[str]:
    """
    Every 自己PR block flattened into one run of paragraphs.

    Two of the four reference documents argue two separate strengths under
    one ■自己PR heading, each introduced by its own ＜見出し＞. Flattening
    here rather than nesting a loop in the template keeps the blank line
    between blocks under this function's control.
    """
    lines: list[str] = []

    for block in data.self_pr_blocks:
        if lines:
            lines.append("")

        if block.heading:
            lines.append(block.heading)

        lines.extend(_paragraphs(block.body))

    return lines
