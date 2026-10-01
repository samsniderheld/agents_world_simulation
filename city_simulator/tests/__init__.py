# Every test runs against the built-in default theme, whichever city is
# active in this checkout (theme.current() would otherwise follow it).
import theme

theme.pin(theme.default())
