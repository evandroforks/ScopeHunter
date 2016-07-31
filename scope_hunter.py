"""
Scope Hunter.

Licensed under MIT
Copyright (c) 2012 - 2016 Isaac Muse <isaacmuse@gmail.com>
"""
import sublime
import sublime_plugin
from time import time, sleep
import threading
from ScopeHunter.lib.color_scheme_matcher import ColorSchemeMatcher
from ScopeHunter.scope_hunter_notify import notify, error
import traceback
from textwrap import dedent
from ScopeHunter import support

LATEST_SUPPORTED_MDPOPUPS = (1, 9, 0)
TOOLTIP_SUPPORT = int(sublime.version()) >= 3080
if TOOLTIP_SUPPORT:
    import mdpopups
    import jinja2

if 'sh_thread' not in globals():
    sh_thread = None

scheme_matcher = None
sh_settings = {}

if TOOLTIP_SUPPORT:
    ADD_CSS = dedent(
        '''
        {%- if var.sublime_version >= 3119 %}
        .scope-hunter.content { padding: 0.5rem; }
        .scope-hunter .small { font-size: 0.7rem; }
        .scope-hunter .header { {{'.string'|css('color')}} }
        {%- else %}
        .scope-hunter.content { margin: 0; padding: 0.5em; }
        .scope-hunter .small { font-size: {{'*0.7px'|relativesize}}; }
        {%- endif %}
        '''
    )

POPUP = '''
## Scope {: .header}
%(scope)s
[(copy)](copy-scope:%(scope_index)d){: .small}

<!-- if var.pt_extent or var.rowcol_extent -->
## Scope Extent {: .header}
  <!-- if var.pt_extent -->
**pts:**{: .keyword} (%(extent_start)d, %(extent_end)d)
[(copy)](copy-points:%(extent_pt_index)d){: .small}
  <!-- endif -->
  <!-- if var.pt_extent or var.rowcol_extent -->
**line/char:**{: .keyword} (**Line:** %(l_start)d **Char:** %(c_start)d, **Line:** %(l_end)d **Char:** %(c_end)d)
[(copy)](copy-line-char:%(line_char_index)d){: .small}
  <!-- endif -->
<!-- endif -->

<!-- if var.appearance -->
## Appearance {: .header}
**%(fg)s:**{: .keyword} %(fg_preview)s %(fg_color)s
[(copy)](%(fg_link)s:%(fg_index)d){: .small}
  <!-- if var.fg_sim -->
**%(fg_sim)s:**{: .keyword} %(fg_sim_preview)s %(fg_sim_color)s
[(copy)](%(fg_sim_link)s:%(fg_sim_index)d){: .small}
  <!-- endif -->
**%(bg)s:**{: .keyword} %(bg_preview)s %(bg_color)s
[(copy)](%(bg_link)s:%(bg_index)d){: .small}
  <!-- if var.bg_sim -->
**%(bg_sim)s:**{: .keyword} %(bg_sim_preview)s %(bg_sim_color)s
[(copy)](%(bg_sim_link)s:%(bg_sim_index)d){: .scope-hunter .small}
  <!-- endif -->
**style:**{: .keyword} <%(style_tag)s>%(style)s</%(style_tag)s>
[(copy)](copy-style:%(style_index)d){: .small}
<!-- endif -->

<!-- if var.selectors -->
## Selectors {: .header}
**fg name:**{: .keyword} %(fg_name)s
[(copy)](copy-fg-sel-name:%(fg_name_index)d){: .small}
**fg scope:**{: .keyword} %(fg_scope)s
[(copy)](copy-fg-sel-scope:%(fg_scope_index)d){: .small}
**bg name:**{: .keyword} %(bg_name)s
[(copy)](copy-bg-sel-name:%(bg_name_index)d){: .small}
**bg scope:**{: .keyword} %(bg_scope)s
[(copy)](copy-bg-sel-scope:%(bg_scope_index)d){: .small}
  <!-- if var.bold -->
**bold name:**{: .keyword} %(bold_name)s
[(copy)](copy-bold-sel-name:%(bold_name_index)d){: .small}
**bold scope:**{: .keyword} %(bold_scope)s
[(copy)](copy-bold-sel-scope:%(bold_scope_index)d){: .small}
  <!-- endif -->
  <!-- if var.italic -->
**italic name:**{: .keyword} %(italic_name)s
[(copy)](copy-italic-sel-name:%(italic_name_index)d){: .small}
**italic scope:**{: .keyword} %(italic_scope)s
[(copy)](copy-italic-sel-scope:%(italic_scope_index)d){: .small}
  <!-- endif -->
<!-- endif -->

<!-- if var.files -->
## Files {: .header}
**scheme:**{: .keyword} [%(scheme)s](scheme)
[(copy)](copy-scheme:%(scheme_index)d){: .small}
**syntax:**{: .keyword} [%(syntax)s](syntax)
[(copy)](copy-syntax:%(syntax_index)d){: .small}
<!-- endif -->'''

COPY_ALL = '''
---

[(copy all)](copy-all){: .small}
'''

# Text Entry
ENTRY = "%-30s %s"
SCOPE_KEY = "Scope"
PTS_KEY = "Scope Extents (Pts)"
PTS_VALUE = "(%d, %d)"
CHAR_LINE_KEY = "Scope Extents (Line/Char)"
CHAR_LINE_VALUE = "(line: %d char: %d, line: %d char: %d)"
FG_KEY = "Fg"
FG_SIM_KEY = "Fg (Simulated Alpha)"
BG_KEY = "Bg"
BG_SIM_KEY = "Bg (Simulated Alpha)"
STYLE_KEY = "Style"
FG_NAME_KEY = "Fg Name"
FG_SCOPE_KEY = "Fg Scope"
BG_NAME_KEY = "Bg Name"
BG_SCOPE_KEY = "Bg Scope"
BOLD_NAME_KEY = "Bold Name"
BOLD_SCOPE_KEY = "Bold Scope"
ITALIC_NAME_KEY = "Italic Name"
ITALIC_SCOPE_KEY = "Italic Scope"
SCHEME_KEY = "Scheme File"
SYNTAX_KEY = "Syntax File"


def log(msg):
    """Logging."""
    print("ScopeHunter: %s" % msg)


def debug(msg):
    """Debug."""
    if sh_settings.get('debug', False):
        log(msg)


def extent_style(option):
    """Configure style of region based on option."""

    style = sublime.HIDE_ON_MINIMAP
    if option == "outline":
        style |= sublime.DRAW_NO_FILL
    elif option == "none":
        style |= sublime.HIDDEN
    elif option == "underline":
        style |= sublime.DRAW_EMPTY_AS_OVERWRITE
    elif option == "thin_underline":
        style |= sublime.DRAW_NO_FILL
        style |= sublime.DRAW_NO_OUTLINE
        style |= sublime.DRAW_SOLID_UNDERLINE
    elif option == "squiggly":
        style |= sublime.DRAW_NO_FILL
        style |= sublime.DRAW_NO_OUTLINE
        style |= sublime.DRAW_SQUIGGLY_UNDERLINE
    elif option == "stippled":
        style |= sublime.DRAW_NO_FILL
        style |= sublime.DRAW_NO_OUTLINE
        style |= sublime.DRAW_STIPPLED_UNDERLINE
    return style


def underline(regions):
    """Convert to empty regions."""

    new_regions = []
    for region in regions:
        start = region.begin()
        end = region.end()
        while start < end:
            new_regions.append(sublime.Region(start))
            start += 1
    return new_regions


def copy_data(bfr, label, index, copy_format=None):
    """Copy data to clipboard from buffer."""

    line = bfr[index]
    if line.startswith(label + ':'):
        text = line.replace(label + ':', '', 1).strip()
        if copy_format is not None:
            text = copy_format(text)
        sublime.set_clipboard(text)
        notify("Copied: %s" % label)


class ScopeHunterEditCommand(sublime_plugin.TextCommand):
    """Edit a view."""

    bfr = None
    pt = None

    def run(self, edit):
        """Insert text into buffer."""

        cls = ScopeHunterEditCommand
        self.view.insert(edit, cls.pt, cls.bfr)

    @classmethod
    def clear(cls):
        """Clear edit buffer."""

        cls.bfr = None
        cls.pt = None


class GetSelectionScope(object):
    """Get the scope and the selection(s)."""

    def init_template_vars(self):
        """Initialize template variables."""

        self.template_strings = {
            "scope": '',
            "scope_index": 0,
            "extent_start": 0,
            "extent_end": 0,
            "extent_pt_index": 0,
            "l_start": 0,
            "c_start": 0,
            "l_end": 0,
            "c_end": 0,
            "line_char_index": 0,
            "fg": '',
            "fg_preview": '',
            "fg_color": '',
            "fg_link": '',
            "fg_index": 0,
            "fg_sim": '',
            "fg_sim_preview": '',
            "fg_sim_color": '',
            "fg_sim_link": '',
            "fg_sim_index": 0,
            "bg": '',
            "bg_preview": '',
            "bg_color": '',
            "bg_link": '',
            "bg_index": 0,
            "bg_sim": '',
            "bg_sim_preview": '',
            "bg_sim_color": '',
            "bg_sim_link": '',
            "bg_sim_index": 0,
            "style_tag": '',
            "style": '',
            "style_index": 0,
            "fg_name": '',
            "fg_name_index": 0,
            "fg_scope": '',
            "fg_scope_index": 0,
            "bg_name": '',
            "bg_name_index": 0,
            "bg_scope": '',
            "bg_scope_index": 0,
            "bold_name": '',
            "bold_name_index": 0,
            "bold_scope": '',
            "bold_scope_index": 0,
            "italic_name": '',
            "italic_name_index": 0,
            "italic_scope": '',
            "italic_scope_index": 0,
            "scheme": '',
            "scheme_index": 0,
            "syntax": '',
            "syntax_index": 0
        }
        self.template_vars = {
            "appearance": False,
            "fg_sim": False,
            "bg_sim": False,
            "files": False,
            "selectors": False,
            "bold": False,
            "bold": False,
            "pt_extent": False,
            "rowcol_extent": False
        }

    def apply_template(self):
        """Apply template."""

        env = jinja2.Environment(
            block_start_string='<!--', block_end_string='-->',
            trim_blocks=True, lstrip_blocks=True
        )
        return env.from_string(POPUP % self.template_strings).render(var=self.template_vars)

    def next_index(self):
        """Get next index into scope buffer."""

        self.index += 1
        return self.index

    def get_color_box(self, color, key, caption, link, index):
        """Display an HTML color box using the given color."""

        border = '#CCCCCC'
        border2 = '#333333'
        padding = int(self.view.settings().get('line_padding_top', 0))
        padding += int(self.view.settings().get('line_padding_bottom', 0))
        box_height = int(self.view.line_height()) - padding - 2
        check_size = int((box_height - 4) / 4)
        if check_size < 2:
            check_size = 2
        self.template_strings[key] = caption
        self.template_strings['%s_preview' % key] = mdpopups.color_box(
            [color], border, border2, height=box_height,
            width=box_height, border_size=2, check_size=check_size
        )
        self.template_strings['%s_color' % key] = color.upper()
        self.template_strings['%s_link' % key] = link
        self.template_strings['%s_index' % key] = index

    def get_extents(self, pt):
        """Get the scope extent via the sublime API."""

        pts = None
        file_end = self.view.size()
        scope_name = self.view.scope_name(pt)
        for r in self.view.find_by_selector(scope_name):
            if r.contains(pt):
                pts = r
                break
            elif pt == file_end and r.end() == pt:
                pts = r
                break

        if pts is None:
            pts = sublime.Region(pt)

        row1, col1 = self.view.rowcol(pts.begin())
        row2, col2 = self.view.rowcol(pts.end())

        # Scale back the extent by one for true points included
        if pts.size() < self.highlight_max_size:
            self.extents.append(sublime.Region(pts.begin(), pts.end()))

        if self.points_info or self.rowcol_info:
            if self.points_info:
                self.scope_bfr.append(ENTRY % (PTS_KEY + ':', PTS_VALUE % (pts.begin(), pts.end())))
            if self.rowcol_info:
                self.scope_bfr.append(
                    ENTRY % (CHAR_LINE_KEY + ':', CHAR_LINE_VALUE % (row1 + 1, col1 + 1, row2 + 1, col2 + 1))
                )

            if self.show_popup:
                if self.points_info:
                    self.template_vars["pt_extent"] = True
                    self.template_strings["extent_start"] = pts.begin()
                    self.template_strings["extent_end"] = pts.end()
                    self.template_strings["extent_pt_index"] = self.next_index()
                if self.rowcol_info:
                    self.template_vars["rowcol_extent"] = True
                    self.template_strings["l_start"] = row1 + 1
                    self.template_strings["l_end"] = row2 + 1
                    self.template_strings["c_start"] = col1 + 1
                    self.template_strings["c_end"] = col2 + 1
                    self.template_strings["line_char_index"] = self.next_index()

    def get_scope(self, pt):
        """Get the scope at the cursor."""

        scope = self.view.scope_name(pt)
        spacing = "\n" + (" " * 31)

        if self.clipboard:
            self.clips.append(scope)

        if self.first and self.show_statusbar:
            self.status = scope
            self.first = False

        self.scope_bfr.append(ENTRY % (SCOPE_KEY + ':', self.view.scope_name(pt).strip().replace(" ", spacing)))

        if self.show_popup:
            self.template_strings['scope'] = self.view.scope_name(pt).strip()
            self.template_strings['scope_index'] = self.next_index()

        return scope

    def get_appearance(self, color, color_sim, bgcolor, bgcolor_sim, style):
        """Get colors of foreground, background, and simulated transparency colors."""

        self.scope_bfr.append(ENTRY % (FG_KEY + ":", color))
        if self.show_simulated and len(color) == 9 and not color.lower().endswith('ff'):
            self.scope_bfr.append(ENTRY % (FG_SIM_KEY + ":", color_sim))

        self.scope_bfr.append(ENTRY % (BG_KEY + ":", bgcolor))
        if self.show_simulated and len(bgcolor) == 9 and not bgcolor.lower().endswith('ff'):
            self.scope_bfr.append(ENTRY % (BG_SIM_KEY + ":", bgcolor_sim))

        self.scope_bfr.append(ENTRY % (STYLE_KEY + ":", style))

        if self.show_popup:
            self.template_vars['appearance'] = True
            self.get_color_box(color, 'fg', 'fg', 'copy-fg', self.next_index())
            if self.show_simulated and len(color) == 9 and not color.lower().endswith('ff'):
                self.template_vars['fg_sim'] = True
                self.get_color_box(color_sim, 'fg_sim', 'fg (simulated alpha)', 'copy-fg-sim', self.next_index())
            self.get_color_box(bgcolor, 'bg', 'bg', 'copy-bg', self.next_index())
            if self.show_simulated and len(bgcolor) == 9 and not bgcolor.lower().endswith('ff'):
                self.template_vars['bg_sim'] = True
                self.get_color_box(bgcolor_sim, 'bg_sim', 'bg (simulated alpha)', 'copy-bg-sim', self.next_index())

            if style == "bold":
                tag = "b"
            elif style == "italic":
                tag = "i"
            elif style == "underline":
                tag = "u"
            else:
                tag = "span"
                style = "normal"
            self.template_strings["style_tag"] = tag
            self.template_strings["style"] = style
            self.template_strings["style_index"] = self.next_index()

    def get_scheme_syntax(self):
        """Get color scheme and syntax file path."""

        self.scheme_file = scheme_matcher.color_scheme.replace('\\', '/')
        self.syntax_file = self.view.settings().get('syntax')
        self.scope_bfr.append(ENTRY % (SCHEME_KEY + ":", self.scheme_file))
        self.scope_bfr.append(ENTRY % (SYNTAX_KEY + ":", self.syntax_file))

        if self.show_popup:
            self.template_vars['files'] = True
            self.template_strings["scheme"] = self.scheme_file
            self.template_strings["scheme_index"] = self.next_index()
            self.template_strings["syntax"] = self.syntax_file
            self.template_strings["syntax_index"] = self.next_index()

    def get_selectors(self, color_selector, bg_selector, style_selectors):
        """Get the selectors used to determine color and/or style."""

        self.scope_bfr.append(ENTRY % (FG_NAME_KEY + ":", color_selector.name))
        self.scope_bfr.append(ENTRY % (FG_SCOPE_KEY + ":", color_selector.scope))
        self.scope_bfr.append(ENTRY % (BG_NAME_KEY + ":", bg_selector.name))
        self.scope_bfr.append(ENTRY % (BG_SCOPE_KEY + ":", bg_selector.scope))
        if style_selectors["bold"].name != "" or style_selectors["bold"].scope != "":
            self.scope_bfr.append(ENTRY % (BOLD_NAME_KEY + ":", style_selectors["bold"].name))
            self.scope_bfr.append(ENTRY % (BOLD_SCOPE_KEY + ":", style_selectors["bold"].scope))

        if style_selectors["italic"].name != "" or style_selectors["italic"].scope != "":
            self.scope_bfr.append(ENTRY % (ITALIC_NAME_KEY + ":", style_selectors["italic"].name))
            self.scope_bfr.append(ENTRY % (ITALIC_SCOPE_KEY + ":", style_selectors["italic"].scope))

        if self.show_popup:
            self.template_vars['selectors'] = True
            self.template_strings['fg_name'] = color_selector.name
            self.template_strings['fg_name_index'] = self.next_index()
            self.template_strings['fg_scope'] = color_selector.scope
            self.template_strings['fg_scope_index'] = self.next_index()
            self.template_strings['bg_name'] = bg_selector.name
            self.template_strings['bg_name_index'] = self.next_index()
            self.template_strings['bg_scope'] = bg_selector.scope
            self.template_strings['bg_scope_index'] = self.next_index()
            if style_selectors["bold"].name != "" or style_selectors["bold"].scope != "":
                self.template_vars['bold'] = True
                self.template_strings['bold_name'] = style_selectors["bold"].name
                self.template_strings['bold_name_index'] = self.next_index()
                self.template_strings['bold_scope'] = style_selectors["bold"].scope
                self.template_strings['bold_scope_index'] = self.next_index()
            if style_selectors["italic"].name != "" or style_selectors["italic"].scope != "":
                self.template_vars['bold'] = True
                self.template_strings['italic_name'] = style_selectors["italic"].name
                self.template_strings['italic_name_index'] = self.next_index()
                self.template_strings['italic_scope'] = style_selectors["italic"].scope
                self.template_strings['italic_scope_index'] = self.next_index()

    def get_info(self, pt):
        """Get scope related info."""

        scope = self.get_scope(pt)

        if self.rowcol_info or self.points_info or self.highlight_extent:
            self.get_extents(pt)

        if (self.appearance_info or self.selector_info) and scheme_matcher is not None:
            try:
                match = scheme_matcher.guess_color(scope)
                color = match.fg
                bgcolor = match.bg
                color_sim = match.fg_simulated
                bgcolor_sim = match.bg_simulated
                style = match.style
                bg_selector = match.bg_selector
                color_selector = match.fg_selector
                style_selectors = match.style_selectors

                if self.appearance_info:
                    self.get_appearance(color, color_sim, bgcolor, bgcolor_sim, style)

                if self.selector_info:
                    self.get_selectors(color_selector, bg_selector, style_selectors)
            except Exception:
                log("Evaluating theme failed!  Ignoring theme related info.")
                debug(str(traceback.format_exc()))
                error("Evaluating theme failed!")
                self.scheme_info = False

        if self.file_path_info and scheme_matcher:
            self.get_scheme_syntax()

        # Divider
        self.next_index()
        self.scope_bfr.append("------")

        if self.show_popup:
            self.scope_bfr_tool.append(self.apply_template())

    def on_navigate(self, href):
        """Exceute link callback."""

        params = href.split(':')
        key = params[0]
        index = int(params[1]) if len(params) > 1 else None
        if key == 'copy-all':
            sublime.set_clipboard('\n'.join(self.scope_bfr))
            notify('Copied: All')
        elif key == 'copy-scope':
            copy_data(
                self.scope_bfr,
                SCOPE_KEY,
                index,
                lambda x: x.replace('\n' + ' ' * 31, ' ')
            )
        elif key == 'copy-points':
            copy_data(self.scope_bfr, PTS_KEY, index)
        elif key == 'copy-line-char':
            copy_data(self.scope_bfr, CHAR_LINE_KEY, index)
        elif key == 'copy-fg':
            copy_data(self.scope_bfr, FG_KEY, index)
        elif key == 'copy-fg-sim':
            copy_data(self.scope_bfr, FG_SIM_KEY, index)
        elif key == 'copy-bg':
            copy_data(self.scope_bfr, BG_KEY, index)
        elif key == 'copy-bg-sim':
            copy_data(self.scope_bfr, BG_SIM_KEY, index)
        elif key == 'copy-style':
            copy_data(self.scope_bfr, STYLE_KEY, index)
        elif key == 'copy-fg-sel-name':
            copy_data(self.scope_bfr, FG_NAME_KEY, index)
        elif key == 'copy-fg-sel-scope':
            copy_data(self.scope_bfr, FG_SCOPE_KEY, index)
        elif key == 'copy-bg-sel-name':
            copy_data(self.scope_bfr, BG_NAME_KEY, index)
        elif key == 'copy-bg-sel-scope':
            copy_data(self.scope_bfr, BG_SCOPE_KEY, index)
        elif key == 'copy-bold-sel-name':
            copy_data(self.scope_bfr, BOLD_NAME_KEY, index)
        elif key == 'copy-bold-sel-scope':
            copy_data(self.scope_bfr, BOLD_SCOPE_KEY, index)
        elif key == 'copy-italic-sel-name':
            copy_data(self.scope_bfr, ITALIC_NAME_KEY, index)
        elif key == 'copy-italic-sel-scope':
            copy_data(self.scope_bfr, ITALIC_SCOPE_KEY, index)
        elif key == 'copy-scheme':
            copy_data(self.scope_bfr, SCHEME_KEY, index)
        elif key == 'copy-syntax':
            copy_data(self.scope_bfr, SYNTAX_KEY, index)
        elif key == 'scheme' and self.scheme_file is not None:
            window = self.view.window()
            window.run_command(
                'open_file',
                {
                    "file": "${packages}/%s" % self.scheme_file.replace(
                        '\\', '/'
                    ).replace('Packages/', '', 1)
                }
            )
        elif key == 'syntax' and self.syntax_file is not None:
            window = self.view.window()
            window.run_command(
                'open_file',
                {
                    "file": "${packages}/%s" % self.syntax_file.replace(
                        '\\', '/'
                    ).replace('Packages/', '', 1)
                }
            )

    def run(self, v):
        """Run ScopeHunter and display in the approriate way."""

        self.view = v
        self.window = self.view.window()
        view = self.window.create_output_panel('scopehunter.results', unlisted=True)
        self.scope_bfr = []
        self.scope_bfr_tool = []
        self.clips = []
        self.status = ""
        self.scheme_file = None
        self.syntax_file = None
        self.show_statusbar = bool(sh_settings.get("show_statusbar", False))
        self.show_panel = bool(sh_settings.get("show_panel", False))
        if TOOLTIP_SUPPORT:
            self.show_popup = bool(sh_settings.get("show_popup", False))
        else:
            self.show_popup = False
        self.clipboard = bool(sh_settings.get("clipboard", False))
        self.multiselect = bool(sh_settings.get("multiselect", False))
        self.console_log = bool(sh_settings.get("console_log", False))
        self.highlight_extent = bool(sh_settings.get("highlight_extent", False))
        self.highlight_scope = sh_settings.get("highlight_scope", 'invalid')
        self.highlight_style = sh_settings.get("highlight_style", 'outline')
        self.highlight_max_size = int(sh_settings.get("highlight_max_size", 100))
        self.rowcol_info = bool(sh_settings.get("extent_line_char", False))
        self.points_info = bool(sh_settings.get("extent_points", False))
        self.appearance_info = bool(sh_settings.get("styling", False))
        self.show_simulated = bool(sh_settings.get("show_simulated_alpha_colors", False))
        self.file_path_info = bool(sh_settings.get("file_paths", False))
        self.selector_info = bool(sh_settings.get("selectors", False))
        self.scheme_info = self.appearance_info or self.selector_info
        self.first = True
        self.extents = []

        # Get scope info for each selection wanted
        self.index = -1
        if len(self.view.sel()):
            if self.multiselect:
                count = 0
                for sel in self.view.sel():
                    if count > 0 and self.show_popup:
                        self.scope_bfr_tool.append('\n---\n')
                    self.init_template_vars()
                    self.get_info(sel.b)
                    count += 1
            else:
                self.init_template_vars()
                self.get_info(self.view.sel()[0].b)

        # Copy scopes to clipboard
        if self.clipboard:
            sublime.set_clipboard('\n'.join(self.clips))

        # Display in status bar
        if self.show_statusbar:
            sublime.status_message(self.status)

        # Show panel
        if self.show_panel:
            ScopeHunterEditCommand.bfr = '\n'.join(self.scope_bfr)
            ScopeHunterEditCommand.pt = 0
            view.run_command('scope_hunter_edit')
            ScopeHunterEditCommand.clear()
            self.window.run_command("show_panel", {"panel": "output.scopehunter.results"})

        if self.console_log:
            print('\n'.join(["Scope Hunter"] + self.scope_bfr))

        if self.highlight_extent:
            style = extent_style(self.highlight_style)
            if style == 'underline':
                self.extents = underline(self.extents)
            self.view.add_regions(
                'scope_hunter',
                self.extents,
                self.highlight_scope,
                '',
                style
            )

        if self.show_popup:
            if self.scheme_info or self.rowcol_info or self.points_info or self.file_path_info:
                tail = COPY_ALL
            else:
                tail = ''
            md = '<div class="scope-hunter content">%s</div>' % mdpopups.md2html(
                self.view, ''.join(self.scope_bfr_tool) + tail
            )
            mdpopups.show_popup(
                self.view,
                md,
                css=ADD_CSS,
                max_width=1000, on_navigate=self.on_navigate
            )

get_selection_scopes = GetSelectionScope()


class GetSelectionScopeCommand(sublime_plugin.TextCommand):
    """Command to get the selection(s) scope."""

    def run(self, edit):
        """On demand scope request."""

        sh_thread.modified = True

    def is_enabled(self):
        """Check if we should scope this view."""

        return sh_thread.is_enabled(self.view)


class ToggleSelectionScopeCommand(sublime_plugin.TextCommand):
    """Command to toggle instant scoper."""

    def run(self, edit):
        """Enable or disable instant scoper."""

        close_display = False

        sh_thread.instant_scoper = False
        if not self.view.settings().get('scope_hunter.view_enable', False):
            self.view.settings().set('scope_hunter.view_enable', True)
            sh_thread.modified = True
            sh_thread.time = time()
        else:
            self.view.settings().set('scope_hunter.view_enable', False)
            close_display = True

        if close_display:
            win = self.view.window()
            if win is not None:
                view = win.get_output_panel('scopehunter.results')
                parent_win = view.window()
                if parent_win:
                    parent_win.run_command('hide_panel', {'cancel': True})
                if TOOLTIP_SUPPORT:
                    mdpopups.hide_popup(self.view)
                if (
                    self.view is not None and
                    sh_thread.is_enabled(view) and
                    bool(sh_settings.get("highlight_extent", False)) and
                    len(view.get_regions("scope_hunter"))
                ):
                    view.erase_regions("scope_hunter")


class SelectionScopeListener(sublime_plugin.EventListener):
    """Listern for instant scoping."""

    def clear_regions(self, view):
        """Clear the highlight regions."""

        if (
            bool(sh_settings.get("highlight_extent", False)) and
            len(view.get_regions("scope_hunter"))
        ):
            view.erase_regions("scope_hunter")

    def on_selection_modified(self, view):
        """Clean up regions or let thread know there was a modification."""

        enabled = sh_thread.is_enabled(view)
        view_enable = view.settings().get('scope_hunter.view_enable', False)
        if (not sh_thread.instant_scoper and not view_enable) or not enabled:
            # clean up dirty highlights
            if enabled:
                self.clear_regions(view)
        else:
            sh_thread.modified = True
            sh_thread.time = time()

    def on_activated(self, view):
        """Check color scheme on activated and update if needed."""

        if not view.settings().get('is_widget', False):
            scheme = view.settings().get("color_scheme")
            if scheme is None:
                pref_settings = sublime.load_settings('Preferences.sublime-settings')
                scheme = pref_settings.get('color_scheme')

            if scheme_matcher is not None and scheme is not None:
                if scheme != scheme_matcher.scheme_file:
                    reinit_plugin()


class ScopeHunterGenerateCssCommand(sublime_plugin.WindowCommand):
    """Command to generate scope CSS."""

    def run(self):
        """Generate the CSS for theme scopes."""

        if scheme_matcher is not None:
            generated_css = mdpopups.st_scheme_template.Scheme2CSS(scheme_matcher.color_scheme.replace('\\', '/')).text
            view = self.window.create_output_panel('scopehunter.gencss', unlisted=True)
            view.sel().clear()
            view.sel().add(sublime.Region(0, view.size()))
            view.run_command('insert', {'characters': generated_css})
            self.window.run_command("show_panel", {"panel": "output.scopehunter.gencss"})

    def is_enabled(self):
        """Check if command is enabled."""

        return TOOLTIP_SUPPORT and scheme_matcher is not None


class ShThread(threading.Thread):
    """Load up defaults."""

    def __init__(self):
        """Setup the thread."""
        self.reset()
        threading.Thread.__init__(self)

    def reset(self):
        """Reset the thread variables."""
        self.wait_time = 0.12
        self.time = time()
        self.modified = False
        self.ignore_all = False
        self.instant_scoper = False
        self.abort = False

    def payload(self):
        """Code to run."""
        # Ignore selection inside the routine
        self.modified = False
        self.ignore_all = True
        window = sublime.active_window()
        view = None if window is None else window.active_view()
        if view is not None:
            get_selection_scopes.run(view)
        self.ignore_all = False
        self.time = time()

    def is_enabled(self, view):
        """Check if we can execute."""
        return not view.settings().get("is_widget") and not self.ignore_all

    def kill(self):
        """Kill thread."""
        self.abort = True
        while self.is_alive():
            pass
        self.reset()

    def run(self):
        """Thread loop."""
        while not self.abort:
            if not self.ignore_all:
                if (
                    self.modified is True and
                    time() - self.time > self.wait_time
                ):
                    sublime.set_timeout(self.payload, 0)
            sleep(0.5)


def init_color_scheme():
    """Setup color scheme match object with current scheme."""

    global scheme_matcher
    scheme_file = None

    # Attempt syntax specific from view
    window = sublime.active_window()
    if window is not None:
        view = window.active_view()
        if view is not None:
            scheme_file = view.settings().get('color_scheme', None)

    # Get global scheme
    if scheme_file is None:
        pref_settings = sublime.load_settings('Preferences.sublime-settings')
        scheme_file = pref_settings.get('color_scheme')

    try:
        scheme_matcher = ColorSchemeMatcher(scheme_file)
    except Exception:
        scheme_matcher = None
        log("Theme parsing failed!  Ignoring theme related info.")
        debug(str(traceback.format_exc()))


def reinit_plugin():
    """Relaod scheme object and tooltip theme."""

    init_color_scheme()


def init_plugin():
    """Setup plugin variables and objects."""

    global sh_thread
    global sh_settings

    # Preferences Settings
    pref_settings = sublime.load_settings('Preferences.sublime-settings')

    # Setup settings
    sh_settings = sublime.load_settings('scope_hunter.sublime-settings')

    # Setup color scheme
    init_color_scheme()

    pref_settings.clear_on_change('scopehunter_reload')
    pref_settings.add_on_change('scopehunter_reload', reinit_plugin)

    sh_settings.clear_on_change('reload')

    # Setup thread
    if sh_thread is not None:
        # This shouldn't be needed, but just in case
        sh_thread.kill()
    sh_thread = ShThread()
    sh_thread.start()


def plugin_loaded():
    """Setup plugin."""

    init_plugin()

    try:
        from package_control import events

        settings = sublime.load_settings('scope_hunter.sublime-settings')
        if TOOLTIP_SUPPORT and events.post_upgrade(support.__pc_name__):
            if not LATEST_SUPPORTED_MDPOPUPS and settings.get('upgrade_dependencies', True):
                window = sublime.active_window()
                if window:
                    window.run_command('satisfy_dependencies')
    except ImportError:
        log('Could not import Package Control')


def plugin_unloaded():
    """Kill the thead."""

    sh_thread.kill()
