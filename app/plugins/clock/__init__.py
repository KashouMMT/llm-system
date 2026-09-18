from app.plugins.clock.commands import SUBCOMMANDS, handle_clock
from app.plugins.clock.tools import get_current_time
from app.plugins.contracts import PluginCommand, ToolPlugin

# Named "clock" rather than "time" so that `import time` inside this
# package's own modules is unambiguous to a reader. Python 3 resolves it
# to the standard library either way; the confusion is the cost.
PLUGIN = ToolPlugin(
    name="clock",
    factory=lambda _context: [get_current_time],
    description="get_current_time — current date and time in Japan (JST)",
    command_factory=lambda _context: (
        PluginCommand(
            namespace="clock",
            handler=handle_clock,
            subcommands=SUBCOMMANDS,
        ),
    ),
)
