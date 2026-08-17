"""
Cookie Auto-Login ULTIMATE Pro - GUI
Version: 5.0 (version_one) - Hardened logic wrapper.

Improvements over 4.1:
  * Imports HTMLReportGenerator from the local report_generator module
    (the old code imported a module that did not exist -> app would not start).
  * "Max concurrent" control wired to CookieManager.max_workers so the
    worker count is capped to what the machine can actually handle.
  * Reuses index->domain mapping, thread-safe scheduling, robust load errors.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, Menu
import threading
import time
from datetime import datetime
import webbrowser
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from main import CookieManager, __version__, __author__
from report_generator import HTMLReportGenerator


class CookieLoginGUI:
    def __init__(self, root):
        self.root = root
        self.root.title(f"Cookie Auto-Login Pro v{__version__}")
        self.root.geometry("1200x800")
        self.root.configure(bg='#f0f0f0')

        self.cookie_manager = CookieManager()
        self.cookie_manager.set_gui_root(self.root)

        # UI variables
        self.success_mode = tk.BooleanVar(value=False)
        self.not_expired_only = tk.BooleanVar(value=True)
        self.login_cookies_only = tk.BooleanVar(value=False)
        self.keep_open = tk.BooleanVar(value=True)
        self.headless_var = tk.BooleanVar(value=False)
        self.keep_open_on_error = tk.BooleanVar(value=False)
        self.manual_confirm_var = tk.BooleanVar(value=False)
        self.deep_scan_var = tk.BooleanVar(value=False)

        self.stealth_var = tk.BooleanVar(value=True)
        self.auto_refresh_var = tk.BooleanVar(value=False)
        self.pre_check_var = tk.BooleanVar(value=True)

        self.delay_var = tk.StringVar(value="2s")

        self.is_verifying = False
        self.current_workers = tk.StringVar(value="2")   # default 2 (resource-aware)
        self.retry_count = tk.StringVar(value="3")

        self.shown_domains = []

        self.setup_ui()
        self.cookie_manager.load_settings()
        self.update_stats()

    # ---------- Thread-safe scheduling ----------
    def schedule(self, func, *args, **kwargs):
        self.root.after(0, lambda f=func, a=args, k=kwargs: f(*a, **k))

    # ---------- Control-state helpers ----------
    def _data_controls(self):
        return (
            self.mass_check_btn, self.export_btn, self.html_btn,
            self.select_all_btn, self.deselect_all_btn,
            self.login_selected_btn, self.login_all_btn,
        )

    def _set_data_enabled(self, enabled):
        state = 'normal' if enabled else 'disabled'
        for w in self._data_controls():
            w.config(state=state)

    def _set_load_enabled(self, enabled):
        state = 'normal' if enabled else 'disabled'
        self.load_btn.config(state=state)
        self.load_file_btn.config(state=state)

    def _my_controls_disable(self):
        self._set_data_enabled(False)
        self._set_load_enabled(False)
        self.mass_check_btn.config(state='disabled')
        self.stop_btn.config(state='disabled')

    def _sync_options(self):
        self.cookie_manager.manual_confirm = self.manual_confirm_var.get()
        self.cookie_manager.use_stealth = self.stealth_var.get()
        self.cookie_manager.auto_refresh = self.auto_refresh_var.get()
        self.cookie_manager.pre_check = self.pre_check_var.get()
        try:
            self.cookie_manager.max_workers = int(self.current_workers.get())
        except ValueError:
            self.cookie_manager.max_workers = 2

    def setup_ui(self):
        title_frame = tk.Frame(self.root, bg='#1a202c', pady=15)
        title_frame.pack(fill='x')

        tk.Label(title_frame, text="🔐 Cookie Auto-Login PRO",
                 font=('Arial', 22, 'bold'), bg='#1a202c', fg='white').pack()
        tk.Label(title_frame, text=f"v{__version__} - Hardened Injection + Multi-Signal Verify",
                 font=('Arial', 10), bg='#1a202c', fg='#cbd5e0').pack()

        main_frame = tk.Frame(self.root, bg='#f0f0f0', padx=20, pady=15)
        main_frame.pack(fill='both', expand=True)

        control_frame = tk.Frame(main_frame, bg='#f0f0f0')
        control_frame.pack(fill='x', pady=(0, 10))

        row1 = tk.Frame(control_frame, bg='#f0f0f0')
        row1.pack(fill='x', pady=(0, 5))

        self.load_btn = tk.Button(row1, text="📁 Load Folder", command=self.load_cookies_folder,
                                   font=('Arial', 10, 'bold'), bg='#667eea', fg='white',
                                   padx=15, pady=8, cursor='hand2', relief='flat')
        self.load_btn.pack(side='left', padx=(0, 5))

        self.load_file_btn = tk.Button(row1, text="📄 Load Single File", command=self.load_cookies_folder_file,
                                        font=('Arial', 10, 'bold'), bg='#4299e1', fg='white',
                                        padx=15, pady=8, cursor='hand2', relief='flat')
        self.load_file_btn.pack(side='left', padx=(0, 5))

        self.mass_check_btn = tk.Button(row1, text="⚡ Mass Verify", command=self.mass_check_logins,
                                         font=('Arial', 10, 'bold'), bg='#f6ad55', fg='white',
                                         padx=15, pady=8, cursor='hand2', relief='flat', state='disabled')
        self.mass_check_btn.pack(side='left', padx=5)

        self.export_btn = tk.Button(row1, text="💾 Export CSV", command=self.export_report,
                                     font=('Arial', 10, 'bold'), bg='#48bb78', fg='white',
                                     padx=15, pady=8, cursor='hand2', relief='flat', state='disabled')
        self.export_btn.pack(side='left', padx=5)

        self.html_btn = tk.Button(row1, text="📊 HTML Report", command=self.export_html_report,
                                   font=('Arial', 10, 'bold'), bg='#8b5cf6', fg='white',
                                   padx=15, pady=8, cursor='hand2', relief='flat', state='disabled')
        self.html_btn.pack(side='left', padx=5)

        self.stop_btn = tk.Button(row1, text="⏹️ Stop", command=self.stop_verification,
                                   font=('Arial', 10, 'bold'), bg='#ef4444', fg='white',
                                   padx=15, pady=8, cursor='hand2', relief='flat', state='disabled')
        self.stop_btn.pack(side='left', padx=5)

        self.close_all_btn = tk.Button(row1, text="❌ Close Browsers", command=self.close_all_browsers,
                                        font=('Arial', 9), bg='#fc8181', fg='white',
                                        padx=10, pady=8, cursor='hand2', relief='flat')
        self.close_all_btn.pack(side='left', padx=10)

        row2 = tk.Frame(control_frame, bg='#f0f0f0')
        row2.pack(fill='x', pady=(5, 5))

        self.select_all_btn = tk.Button(row2, text="☑️ Select All", command=self.select_all,
                                         font=('Arial', 9), bg='#e2e8f0', fg='#2d3748',
                                         padx=10, pady=6, cursor='hand2', relief='flat', state='disabled')
        self.select_all_btn.pack(side='left', padx=(0, 5))

        self.deselect_all_btn = tk.Button(row2, text="☐ Deselect", command=self.deselect_all,
                                           font=('Arial', 9), bg='#e2e8f0', fg='#2d3748',
                                           padx=10, pady=6, cursor='hand2', relief='flat', state='disabled')
        self.deselect_all_btn.pack(side='left', padx=5)

        self.login_selected_btn = tk.Button(row2, text="🚀 Login Selected", command=self.login_selected,
                                             font=('Arial', 10, 'bold'), bg='#48bb78', fg='white',
                                             padx=20, pady=6, cursor='hand2', relief='flat', state='disabled')
        self.login_selected_btn.pack(side='left', padx=10)

        self.login_all_btn = tk.Button(row2, text="🚀 Login ALL Working", command=self.login_all_working,
                                        font=('Arial', 10, 'bold'), bg='#e53e3e', fg='white',
                                        padx=20, pady=6, cursor='hand2', relief='flat', state='disabled')
        self.login_all_btn.pack(side='left', padx=5)

        tk.Label(row2, text="Max concurrent:", font=('Arial', 9), bg='#f0f0f0').pack(side='left', padx=(20, 5))
        workers_combo = ttk.Combobox(row2, textvariable=self.current_workers,
                                     values=["1", "2", "3", "4", "5"], state='readonly', width=5)
        workers_combo.pack(side='left', padx=(0, 10))

        tk.Label(row2, text="Retries:", font=('Arial', 9), bg='#f0f0f0').pack(side='left', padx=(0, 5))
        retries_combo = ttk.Combobox(row2, textvariable=self.retry_count,
                                     values=["1", "2", "3", "4", "5"], state='readonly', width=5)
        retries_combo.pack(side='left')

        stats_frame = tk.Frame(main_frame, bg='#edf2f7', relief='solid', borderwidth=1)
        stats_frame.pack(fill='x', pady=(0, 10))

        self.stats_label = tk.Label(stats_frame, text="📊 Total: 0 | ✓ Working: 0 | ✗ Failed: 0 | 🌐 Open: 0",
                                     font=('Arial', 10, 'bold'), bg='#edf2f7', fg='#2d3748', pady=8)
        self.stats_label.pack()

        filter_frame = tk.Frame(main_frame, bg='#f0f0f0')
        filter_frame.pack(fill='x', pady=(0, 10))

        self.success_mode_check = tk.Checkbutton(filter_frame, text="✓ Only Working Sites", variable=self.success_mode,
                                                   command=self.apply_filters, font=('Arial', 10, 'bold'),
                                                   bg='#f0f0f0', fg='#38a169', selectcolor='#f0f0f0')
        self.success_mode_check.pack(side='left', padx=(0, 15))

        self.not_expired_check = tk.Checkbutton(filter_frame, text="⏱ Not expired", variable=self.not_expired_only,
                                                 command=self.apply_filters, font=('Arial', 10, 'bold'),
                                                 bg='#f0f0f0', fg='#3182ce', selectcolor='#f0f0f0')
        self.not_expired_check.pack(side='left', padx=(0, 15))

        self.login_cookies_check = tk.Checkbutton(filter_frame, text="🔑 Has login data", variable=self.login_cookies_only,
                                                    command=self.apply_filters, font=('Arial', 10, 'bold'),
                                                    bg='#f0f0f0', fg='#d69e2e', selectcolor='#f0f0f0')
        self.login_cookies_check.pack(side='left', padx=(0, 15))

        tk.Label(filter_frame, text="Category:", font=('Arial', 10), bg='#f0f0f0').pack(side='left', padx=(0, 5))
        self.category_var = tk.StringVar(value="All")
        self.category_dropdown = ttk.Combobox(filter_frame, textvariable=self.category_var,
                                               values=["All", "Social Media", "Shopping", "Banking", "Email", "Entertainment", "Gambling"],
                                               state='readonly', width=15)
        self.category_dropdown.pack(side='left', padx=(0, 15))
        self.category_dropdown.bind('<<ComboboxSelected>>', lambda e: self.apply_filters())

        tk.Label(filter_frame, text="🔍", font=('Arial', 12), bg='#f0f0f0').pack(side='left', padx=(0, 5))
        self.search_var = tk.StringVar()
        self.search_var.trace_add('write', self.apply_filters)
        self.search_entry = tk.Entry(filter_frame, textvariable=self.search_var, font=('Arial', 10), width=25)
        self.search_entry.pack(side='left', fill='x', expand=True)

        self.websites_header = tk.Label(main_frame, text="Websites (0):", font=('Arial', 11, 'bold'), bg='#f0f0f0')
        self.websites_header.pack(anchor='w', pady=(5, 5))

        list_frame = tk.Frame(main_frame, bg='white', relief='solid', borderwidth=1)
        list_frame.pack(fill='both', expand=True, pady=(0, 10))

        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side='right', fill='y')

        self.websites_listbox = tk.Listbox(list_frame, font=('Courier', 10), bg='white', fg='#2d3748',
                                            selectmode='multiple', yscrollcommand=scrollbar.set,
                                            relief='flat', height=20)
        self.websites_listbox.pack(side='left', fill='both', expand=True, padx=5, pady=5)
        scrollbar.config(command=self.websites_listbox.yview)

        self.context_menu = Menu(self.websites_listbox, tearoff=0)
        self.context_menu.add_command(label="🚀 Login Selected", command=self.login_selected)
        self.context_menu.add_command(label="🌐 Open in Browser", command=self.open_url)
        self.context_menu.add_command(label="🔍 Preview Cookies", command=self.preview_cookies)
        self.websites_listbox.bind('<Button-3>', self.show_context_menu)
        self.websites_listbox.bind('<Double-Button-1>', lambda e: self.login_selected())

        bottom_frame = tk.Frame(main_frame, bg='#f0f0f0')
        bottom_frame.pack(fill='x', pady=(5, 0))

        left_controls = tk.Frame(bottom_frame, bg='#f0f0f0')
        left_controls.pack(side='left', fill='x', expand=True)

        tk.Checkbutton(left_controls, text="🕶️ Headless Mode", variable=self.headless_var,
                       font=('Arial', 10), bg='#f0f0f0', selectcolor='#f0f0f0').pack(side='left', padx=(0, 10))
        tk.Checkbutton(left_controls, text="🖥️ Keep Browser Open", variable=self.keep_open,
                       font=('Arial', 10, 'bold'), bg='#f0f0f0', selectcolor='#f0f0f0').pack(side='left', padx=(0, 15))
        tk.Checkbutton(left_controls, text="🐛 Keep on Error", variable=self.keep_open_on_error,
                       font=('Arial', 10, 'bold'), bg='#f0f0f0', fg='#e53e3e', selectcolor='#f0f0f0').pack(side='left', padx=(0, 15))
        tk.Checkbutton(left_controls, text="👤 Manual Confirm", variable=self.manual_confirm_var,
                       font=('Arial', 10, 'bold'), bg='#f0f0f0', fg='#3b82f6', selectcolor='#f0f0f0').pack(side='left', padx=(0, 15))
        tk.Checkbutton(left_controls, text="🔍 Deep Scan", variable=self.deep_scan_var,
                       font=('Arial', 10, 'bold'), bg='#f0f0f0', fg='#8b5cf6', selectcolor='#f0f0f0').pack(side='left', padx=(0, 15))
        tk.Checkbutton(left_controls, text="🛡️ Stealth", variable=self.stealth_var,
                       font=('Arial', 10, 'bold'), bg='#f0f0f0', fg='#2d3748', selectcolor='#f0f0f0').pack(side='left', padx=(0, 10))
        tk.Checkbutton(left_controls, text="🔄 Auto-Refresh", variable=self.auto_refresh_var,
                       font=('Arial', 10, 'bold'), bg='#f0f0f0', fg='#d69e2e', selectcolor='#f0f0f0').pack(side='left', padx=(0, 10))
        tk.Checkbutton(left_controls, text="🚀 Pre-Check", variable=self.pre_check_var,
                       font=('Arial', 10, 'bold'), bg='#f0f0f0', fg='#48bb78', selectcolor='#f0f0f0').pack(side='left', padx=(0, 10))
        tk.Label(left_controls, text="Delay:", font=('Arial', 10), bg='#f0f0f0').pack(side='left', padx=(0, 5))
        ttk.Combobox(left_controls, textvariable=self.delay_var, values=["1s", "2s", "3s", "5s"], width=5).pack(side='left')

        self.progress_frame = tk.Frame(main_frame, bg='#f0f0f0')
        self.progress_frame.pack(fill='x', pady=(5, 0))

        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(self.progress_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(side='left', fill='x', expand=True, padx=(0, 10))

        self.progress_label = tk.Label(self.progress_frame, text="", font=('Arial', 9), bg='#f0f0f0')
        self.progress_label.pack(side='right')

        self.status_label = tk.Label(main_frame, text="✅ Ready - Load cookie folder or file", font=('Arial', 9), bg='#f0f0f0', fg='#4299e1')
        self.status_label.pack(pady=5)

    # ---------- Helpers ----------
    def show_context_menu(self, event):
        try:
            self.websites_listbox.selection_clear(0, tk.END)
            self.websites_listbox.selection_set(self.websites_listbox.nearest(event.y))
            self.context_menu.post(event.x_root, event.y_root)
        except Exception:
            pass

    def open_url(self):
        domain = self.get_domain_from_selection()
        if domain:
            webbrowser.open(f"https://{domain}")

    def preview_cookies(self):
        domain = self.get_domain_from_selection()
        if not domain:
            return
        preview = self.cookie_manager.get_domain_cookies_preview(domain)
        if preview:
            text = f"Domain: {preview['domain']}\n"
            text += f"Score: {preview['score']}/100\n"
            text += f"Total Cookies: {preview['total_cookies']}\n"
            text += f"Not expired: {preview['live_cookies']} | Expired: {preview['expired_cookies']}\n"
            text += f"Has login data: {'yes' if preview['has_login_data'] else 'no'}\n\n"
            text += "Top Cookies:\n"
            for c in preview['top_cookies']:
                flag = " [expired]" if c.get('expired') else ""
                text += f"  {c['name']} = {c['value']}...{flag}\n"
            messagebox.showinfo("Cookie Preview", text)

    def get_domain_from_selection(self, index=None):
        selection = self.websites_listbox.curselection()
        if not selection:
            return ""
        pos = selection[0] if index is None else index
        if 0 <= pos < len(self.shown_domains):
            return self.shown_domains[pos]
        return ""

    def select_all(self):
        self.websites_listbox.selection_set(0, tk.END)

    def deselect_all(self):
        self.websites_listbox.selection_clear(0, tk.END)

    # ---------- Loading ----------
    def load_cookies_folder(self):
        folder = filedialog.askdirectory(title="Select Cookie Folder")
        if not folder:
            return
        self._load_cookies(lambda progress: self.cookie_manager.process_cookie_files(folder, progress))

    def load_cookies_folder_file(self):
        file_path = filedialog.askopenfilename(title="Select Cookie File", filetypes=[("Text files", "*.txt")])
        if not file_path:
            return
        self._load_cookies(lambda progress: self.cookie_manager.process_single_file(file_path))

    def _load_cookies(self, load_func):
        self.status_label.config(text="📂 Loading cookies...")
        self._my_controls_disable()

        def progress(current, total):
            pct = (current / total * 100) if total else 100
            self.schedule(self.progress_var.set, pct)
            self.schedule(self.progress_label.config, text=f"📄 {current}/{total}")

        def wrapped_load():
            try:
                valid, total = load_func(progress)
            except Exception as e:
                self.schedule(self._finish_load_error, e)
                return
            self.schedule(self.finish_loading, valid, total)

        threading.Thread(target=wrapped_load, daemon=True).start()

    def _finish_load_error(self, exc):
        self._set_load_enabled(True)
        self._set_data_enabled(False)
        self.progress_var.set(0)
        self.progress_label.config(text="")
        self.status_label.config(text="❌ Failed to load cookies", fg='#e53e3e')
        messagebox.showerror("Load Error", f"Could not load cookies:\n{exc}")

    def finish_loading(self, valid, total):
        self.websites_header.config(text=f"Websites ({valid}):")
        self._set_load_enabled(True)
        self._set_data_enabled(True)
        self.progress_var.set(0)
        self.progress_label.config(text="")
        self.status_label.config(text=f"✅ Loaded {valid} websites from {total} files", fg='#38a169')
        self.apply_filters()
        self.update_stats()
        if valid == 0:
            messagebox.showwarning("No Valid Cookies", "No usable cookies found in the selected files.")

    # ---------- Filters & List ----------
    def apply_filters(self, *args):
        if not self.cookie_manager.websites:
            return
        filtered = self.cookie_manager.websites.copy()
        if self.success_mode.get():
            filtered = [w for w in filtered if self.cookie_manager.login_status.get(w) == 'success']
        if self.not_expired_only.get():
            filtered = [w for w in filtered if self.cookie_manager.has_unexpired_cookies(w)]
        if self.login_cookies_only.get():
            filtered = [w for w in filtered if self.cookie_manager.has_login_data(w)]
        category = self.category_var.get()
        if category != "All":
            filtered = [w for w in filtered if self.cookie_manager.categories.get(w) == category]
        query = self.search_var.get().lower()
        if query:
            filtered = [w for w in filtered if query in w.lower()]
        self.websites_header.config(
            text=f"Websites ({len(filtered)}/{len(self.cookie_manager.websites)}):"
        )
        self.update_list(filtered)

    def update_list(self, websites):
        self.websites_listbox.delete(0, tk.END)
        self.shown_domains = []
        for website in websites:
            count = len(self.cookie_manager.all_cookies.get(website, []))
            expired = self.cookie_manager.expired_cookie_count(website)
            status = self.cookie_manager.login_status.get(website, 'unknown')
            score = self.cookie_manager.cookie_scores.get(website, 0)
            emoji = self.cookie_manager.get_score_emoji(score)
            color = self.cookie_manager.get_score_color(score)
            icon = '✓' if status == 'success' else ('?' if status == 'unknown' else '✗')
            login_mark = ' 🔑' if self.cookie_manager.has_login_data(website) else ''
            exp_bit = f", {expired} expired" if expired else ""
            text = f"[{icon}] {emoji} {website} ({count} cookies{exp_bit}) - Score: {score}{login_mark}"
            self.websites_listbox.insert(tk.END, text)
            idx = self.websites_listbox.size() - 1
            self.websites_listbox.itemconfig(idx, fg=color)
            self.shown_domains.append(website)

    def update_stats(self):
        total = len(self.cookie_manager.websites)
        verified = sum(1 for s in self.cookie_manager.login_status.values() if s == 'success')
        failed = sum(1 for s in self.cookie_manager.login_status.values() if s == 'failed')
        open_browsers = len(self.cookie_manager.drivers)
        live = sum(1 for d in self.cookie_manager.websites if self.cookie_manager.has_unexpired_cookies(d))
        login_ready = sum(1 for d in self.cookie_manager.websites if self.cookie_manager.has_login_data(d))
        self.stats_label.config(
            text=f"📊 Total: {total} | ⏱ Live: {live} | 🔑 Login-ready: {login_ready} | ✓ Working: {verified} | ✗ Failed: {failed} | 🌐 Open: {open_browsers}"
        )

    # ---------- Mass Verify ----------
    def mass_check_logins(self):
        if not self.cookie_manager.websites:
            return
        total = len(self.cookie_manager.websites)
        workers = int(self.current_workers.get())
        keep_open_on_error = self.keep_open_on_error.get()
        deep_scan = self.deep_scan_var.get()

        if deep_scan:
            msg = f"Deep Scan will verify {total} sites sequentially with visible browsers.\nThis may take a while. Continue?"
        else:
            msg = f"Verify {total} websites?\nMax concurrent: {workers}"
        if not messagebox.askyesno("Mass Verify", msg):
            return

        self._sync_options()

        self.is_verifying = True
        self.cookie_manager.stop_verification = False
        self.mass_check_btn.config(state='disabled')
        self.stop_btn.config(state='normal')

        def progress(completed, total, verified, failed):
            pct = (completed / total * 100) if total else 100
            self.schedule(self.progress_var.set, pct)
            self.schedule(self.progress_label.config, text=f"🔍 {completed}/{total} | ✓{verified} ✗{failed}")
            self.schedule(self.apply_filters)
            self.schedule(self.update_stats)

        def run():
            verified, failed = self.cookie_manager.mass_check_logins(
                progress, max_workers=workers,
                keep_open_on_error=keep_open_on_error,
                deep_scan=deep_scan
            )
            self.schedule(self.finish_mass_check, verified, failed)

        threading.Thread(target=run, daemon=True).start()

    def finish_mass_check(self, verified, failed):
        self.is_verifying = False
        self.apply_filters()
        self.update_stats()
        self.mass_check_btn.config(state='normal')
        self.stop_btn.config(state='disabled')
        self.progress_var.set(0)
        self.progress_label.config(text="")
        self.status_label.config(text=f"✅ Mass verify complete! {verified} working, {failed} failed", fg='#38a169')
        messagebox.showinfo("Complete", f"✓ Working: {verified}\n✗ Failed: {failed}")

    def stop_verification(self):
        if self.is_verifying:
            self.cookie_manager.stop_verification = True
            self.stop_btn.config(state='disabled')

    # ---------- Login Actions ----------
    def login_selected(self):
        selections = self.websites_listbox.curselection()
        if not selections:
            messagebox.showwarning("No Selection", "Select websites to login")
            return
        domains = [self.get_domain_from_selection(i) for i in selections]
        domains = [d for d in domains if d]
        if not domains:
            return

        headless = self.headless_var.get()
        keep_open = self.keep_open.get()
        retries = int(self.retry_count.get())
        deep_scan = self.deep_scan_var.get()
        self._sync_options()

        self.status_label.config(text=f"🚀 Logging into {len(domains)} sites...")

        def run():
            results = self.cookie_manager.login_multiple(
                domains, headless, keep_open, retries,
                self.keep_open_on_error.get(), deep_scan
            )
            success_count = sum(1 for r in results if r[1])
            self.schedule(self.update_stats)
            self.schedule(self.status_label.config, text="✅ Login complete", fg='#38a169')
            self.schedule(messagebox.showinfo, "Login Complete",
                          f"Successfully logged into {success_count}/{len(domains)} sites")

        threading.Thread(target=run, daemon=True).start()

    def login_all_working(self):
        working = [d for d, s in self.cookie_manager.login_status.items() if s == 'success']
        if not working:
            messagebox.showwarning("No Working Sites", "Run Mass Verify first")
            return
        if not messagebox.askyesno("Login All", f"Login to all {len(working)} working sites?"):
            return
        headless = self.headless_var.get()
        keep_open = self.keep_open.get()
        retries = int(self.retry_count.get())
        deep_scan = self.deep_scan_var.get()
        self._sync_options()

        self.status_label.config(text=f"🚀 Logging into {len(working)} working sites...")

        def run():
            results = self.cookie_manager.login_multiple(
                working, headless, keep_open, retries,
                self.keep_open_on_error.get(), deep_scan
            )
            success_count = sum(1 for r in results if r[1])
            self.schedule(self.update_stats)
            self.schedule(self.status_label.config, text="✅ Login complete", fg='#38a169')
            self.schedule(messagebox.showinfo, "Login Complete",
                          f"Successfully logged into {success_count}/{len(working)} sites")

        threading.Thread(target=run, daemon=True).start()

    def close_all_browsers(self):
        count = self.cookie_manager.close_all_browsers()
        self.update_stats()
        if count > 0:
            self.status_label.config(text="", fg='#38a169')
            self.status_label.config(text=f"✅ Closed {count} browsers", fg='#38a169')

    # ---------- Export ----------
    def export_report(self):
        if not self.cookie_manager.websites:
            messagebox.showwarning("No Data", "No data to export")
            return
        filename = f"cookie_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile=filename)
        if path:
            if self.cookie_manager.export_report(path):
                self.status_label.config(text=f"✅ Report saved to {path}", fg='#38a169')
                messagebox.showinfo("Export Complete", f"Report saved to:\n{path}")

    def export_html_report(self):
        if not self.cookie_manager.websites:
            messagebox.showwarning("No Data", "No data to export")
            return
        data = self.cookie_manager.get_all_data_for_report()
        if not data['domains']:
            messagebox.showwarning("No Data", "No domains with cookies found.")
            return
        filename = f"cookie_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        path = filedialog.asksaveasfilename(defaultextension=".html", initialfile=filename,
                                            filetypes=[("HTML files", "*.html")])
        if path:
            try:
                output = HTMLReportGenerator.generate(data, path)
                self.status_label.config(text=f"✅ HTML report saved to {output}", fg='#38a169')
                if messagebox.askyesno("Open Report", f"Report saved.\nOpen it in your browser?"):
                    webbrowser.open(output)
            except Exception as e:
                messagebox.showerror("Error", f"Failed to generate HTML report: {e}")


def main():
    root = tk.Tk()
    app = CookieLoginGUI(root)

    def on_closing():
        app.cookie_manager.close_all_browsers()
        app.cookie_manager.save_settings()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
