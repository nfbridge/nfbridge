# SPDX-License-Identifier: GPL-3.0-only
"""Small hover/focus help that never changes focus or invokes a command."""
import tkinter as tk


class Tooltip:
    def __init__(self, widget, text, delay=550):
        self.widget, self.text, self.delay = widget, text, delay
        self.timer = self.window = None
        for event in ('<Enter>', '<FocusIn>'):
            widget.bind(event, self.schedule, add='+')
        for event in ('<Leave>', '<FocusOut>', '<ButtonPress>', '<Escape>', '<Destroy>'):
            widget.bind(event, self.hide, add='+')

    def schedule(self, event=None):
        self.hide()
        self.timer = self.widget.after(self.delay, self.show)

    def show(self):
        self.timer = None
        if not self.widget.winfo_exists() or not self.widget.winfo_viewable():
            return
        tip = self.window = tk.Toplevel(self.widget)
        tip.withdraw()
        tip.overrideredirect(True)
        if self.widget.tk.call('tk', 'windowingsystem') == 'aqua':
            # A help window must not activate and steal focus from its button.
            self.widget.tk.call('::tk::unsupported::MacWindowStyle', 'style',
                                tip._w, 'help', 'noActivates')
        label = tk.Label(tip, text=self.text(), justify='left', wraplength=340,
                         background='#fff7db', foreground='#20251f',
                         borderwidth=1, relief='solid', padx=10, pady=7)
        label.pack()
        tip.update_idletasks()
        x = max(0, min(self.widget.winfo_rootx(), self.widget.winfo_screenwidth()-tip.winfo_reqwidth()))
        y = self.widget.winfo_rooty()-tip.winfo_reqheight()-6
        if y < 0:
            y = self.widget.winfo_rooty()+self.widget.winfo_height()+6
        tip.geometry(f'+{x}+{y}')
        tip.deiconify()

    def hide(self, event=None):
        if self.timer is not None:
            try:
                self.widget.after_cancel(self.timer)
            except tk.TclError:
                pass
            self.timer = None
        if self.window is not None:
            try:
                self.window.destroy()
            except tk.TclError:
                pass
            self.window = None
