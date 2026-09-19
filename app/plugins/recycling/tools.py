"""The /recycle subcommands as agent tools: the model decides *when* to
scan or show the catalog; the command's own code decides *what* is shown.

Each tool is a thin adapter over the same runner the slash command uses
(commands.make_recycle_runners). On success the runner's Markdown goes to
the user as a reply block and the model receives only a summary, so a
40-row table never passes through the model to be retyped. On failure
("nothing attached") the text goes back to the model to explain.

build_catalog_force is deliberately NOT a tool. It overwrites rows a
reviewer may have corrected by hand, so it stays something a person types;
plugin_prompt.txt tells the model to suggest the command and warn instead.
"""

import time

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from app.plugins.recycling import prompts
from app.plugins.recycling.commands import SUBCOMMANDS, RecycleRunner
from app.plugins.run_context import run_identity
from app.services.reply_blocks import ReplyBlocks
from app.utils.logger import logger
from app.utils.video_frames import MAX_FRAME_COUNT, MIN_FRAME_COUNT

# The admin rule is read from the command's own spec, so a tool and its
# slash command can never disagree about who may run it.
_ADMIN_ONLY = {spec.name for spec in SUBCOMMANDS if spec.admin_only}


class _CaptureArgs(BaseModel):
    frames: int | None = Field(
        default=None,
        ge=MIN_FRAME_COUNT,
        le=MAX_FRAME_COUNT,
        description="Video only: how many frames to analyse. Omit for the default.",
    )


class _NoArgs(BaseModel):
    pass


def make_recycle_tools(
    runners: dict[str, RecycleRunner],
    reply_blocks: ReplyBlocks,
) -> list[BaseTool]:
    def build(
        tool_name: str,
        subcommand: str,
        description: str,
        args: type[BaseModel],
        *,
        runner_key: str | None = None,
    ) -> BaseTool:
        # `subcommand` decides the admin rule and the CommandContext; the
        # runner is usually the command's own, unless runner_key names one
        # made for the tool (show_catalog links instead of tabulating).
        runner = runners[runner_key or subcommand]

        async def run(config: RunnableConfig, frames: int | None = None) -> str:
            start = time.perf_counter()
            # Identity from the run config, never from the arguments.
            who = run_identity(config)

            logger.info(
                "Tool started | tool=%s conversation=%s",
                tool_name,
                who.conversation_id,
            )

            if subcommand in _ADMIN_ONLY and not who.is_admin:
                logger.warning(
                    "Tool refused, admin only | tool=%s user=%s conversation=%s",
                    tool_name,
                    who.user.id,
                    who.conversation_id,
                )
                return prompts.ADMIN_ONLY

            # The same CommandContext the slash command gets, so the runner
            # reads the attachments of the user's current message and parses
            # `frames` exactly as it would from `/recycle scan 20`.
            argument = "" if frames is None else str(frames)
            outcome = await runner(who.command_context(subcommand, argument))

            if not outcome.ok:
                result = prompts.FAILED.format(markdown=outcome.markdown)
            elif reply_blocks.publish(
                who.assistant_message_id, outcome.markdown, context=outcome.context
            ):
                result = outcome.model_summary
            else:
                result = prompts.NOT_DISPLAYED.format(subcommand=subcommand)

            logger.info(
                "Tool completed | tool=%s ok=%s elapsed=%.2fs",
                tool_name,
                outcome.ok,
                time.perf_counter() - start,
            )
            return result

        return StructuredTool.from_function(
            coroutine=run,
            name=tool_name,
            description=description,
            args_schema=args,
        )

    return [
        build("recycle_scan", "scan", prompts.SCAN_DESCRIPTION, _CaptureArgs),
        build(
            "recycle_build_catalog",
            "build_catalog",
            prompts.BUILD_CATALOG_DESCRIPTION,
            _CaptureArgs,
        ),
        build(
            "recycle_catalog_health",
            "health",
            prompts.HEALTH_DESCRIPTION,
            _NoArgs,
        ),
        build(
            "recycle_show_catalog",
            "show_catalog",
            prompts.SHOW_CATALOG_DESCRIPTION,
            _NoArgs,
            runner_key="catalog_link",
        ),
    ]
