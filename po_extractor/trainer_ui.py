"""
po_extractor/trainer_ui.py
───────────────────────────
Visual template training interface for PO PDF extraction.

Workflow:
  1. User opens a PO PDF
  2. PDF renders in a scrollable canvas
  3. JARVIS asks: "Where is the PO Number? Draw a box around it."
  4. User drags a rectangle on the PDF image
  5. JARVIS OCRs that region, shows what it found
  6. User confirms ("Yes, that's correct") or adjusts
  7. Region + label saved to template JSON
  8. Repeat for each field until template is complete

Design:
  - Tkinter only — no PyQt, no Electron. Lightweight.
  - Works on 8GB RAM without issues.
  - Scrollable canvas for large PDF pages.
  - Zoom controls (50%, 75%, 100%, 150%).
  - Field-by-field guided training mode.
  - Manual field selection mode for corrections.
  - Template progress bar.

Usage (standalone):
  python -m po_extractor.trainer_ui

Usage (from JARVIS voice command):
  "Train PDF template" → opens this UI
  "Train Cecil collection PDF" → opens with buyer/type pre-selected
"""

from __future__ import annotations

import json
import logging
import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime
from typing import Optional

log = logging.getLogger("jarvis.trainer_ui")

# ── Colours and layout ────────────────────────────────────────────────────────
BG_DARK     = "#1a1a2e"
BG_PANEL    = "#16213e"
BG_CANVAS   = "#0f3460"
ACCENT      = "#e94560"
ACCENT2     = "#533483"
TEXT_LIGHT  = "#eaeaea"
TEXT_DIM    = "#888888"
BOX_COLOR   = "#e94560"     # selection rectangle
BOX_DONE    = "#00b894"     # confirmed region
BOX_HOVER   = "#fdcb6e"     # hover


class TrainerUI:
    """
    Main training interface window.
    Can be launched standalone or embedded from JARVIS.
    """

    def __init__(
        self,
        template_store,
        ocr_engine,
        buyer: str = "",
        order_type: str = "collection",
        pdf_path: str = "",
    ):
        self._store      = template_store
        self._ocr        = ocr_engine
        self._buyer      = buyer
        self._order_type = order_type
        self._pdf_path   = pdf_path

        # State
        self._renderer    = None
        self._rendered    = None      # RenderedPage
        self._photo       = None      # ImageTk.PhotoImage
        self._template    = None      # Template
        self._zoom        = 1.0
        self._current_field_idx = 0
        self._fields_queue = []       # ordered list of field_names to train

        # Draw state
        self._start_x = self._start_y = 0
        self._rect_id = None
        self._drawn_boxes: list[dict] = []   # {field, rect_id, bbox_norm}

        self._build_window()

    # ── Window Construction ───────────────────────────────────────────────────

    def _build_window(self):
        self.root = tk.Tk()
        self.root.title("JARVIS — PO Template Trainer")
        self.root.configure(bg=BG_DARK)
        self.root.geometry("1200x800")
        self.root.minsize(900, 600)

        self._build_styles()
        self._build_menu()
        self._build_left_panel()
        self._build_canvas_area()
        self._build_bottom_bar()

        if self._buyer and self._pdf_path:
            self.root.after(200, self._load_pdf_and_template)

    def _build_styles(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background=BG_DARK)
        style.configure("Panel.TFrame", background=BG_PANEL)
        style.configure(
            "TLabel",
            background=BG_DARK, foreground=TEXT_LIGHT,
            font=("Consolas", 10),
        )
        style.configure(
            "Header.TLabel",
            background=BG_PANEL, foreground=ACCENT,
            font=("Consolas", 12, "bold"),
        )
        style.configure(
            "Field.TLabel",
            background=BG_PANEL, foreground=TEXT_LIGHT,
            font=("Consolas", 10),
        )
        style.configure(
            "Done.TLabel",
            background=BG_PANEL, foreground=BOX_DONE,
            font=("Consolas", 10),
        )
        style.configure(
            "TButton",
            background=ACCENT, foreground="white",
            font=("Consolas", 10, "bold"),
            borderwidth=0, relief="flat",
        )
        style.map("TButton", background=[("active", ACCENT2)])
        style.configure(
            "TProgressbar",
            background=ACCENT, troughcolor=BG_PANEL,
            bordercolor=BG_PANEL, lightcolor=ACCENT, darkcolor=ACCENT,
        )

    def _build_menu(self):
        menubar = tk.Menu(self.root, bg=BG_DARK, fg=TEXT_LIGHT,
                          activebackground=ACCENT, activeforeground="white")
        self.root.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0, bg=BG_PANEL, fg=TEXT_LIGHT)
        file_menu.add_command(label="Open PDF…", command=self._cmd_open_pdf)
        file_menu.add_separator()
        file_menu.add_command(label="Save Template", command=self._cmd_save_template)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)

        view_menu = tk.Menu(menubar, tearoff=0, bg=BG_PANEL, fg=TEXT_LIGHT)
        view_menu.add_command(label="Zoom In  (+)", command=self._zoom_in)
        view_menu.add_command(label="Zoom Out (−)", command=self._zoom_out)
        view_menu.add_command(label="Fit Width", command=self._zoom_fit)
        menubar.add_cascade(label="View", menu=view_menu)

    def _build_left_panel(self):
        self._left = ttk.Frame(self.root, width=260, style="Panel.TFrame")
        self._left.pack(side=tk.LEFT, fill=tk.Y, padx=0, pady=0)
        self._left.pack_propagate(False)

        # ── Title ──────────────────────────────────────────────────────────
        ttk.Label(self._left, text="JARVIS TRAINER", style="Header.TLabel",
                  padding=(12, 12, 12, 4)).pack(fill=tk.X)

        sep = tk.Frame(self._left, bg=ACCENT, height=1)
        sep.pack(fill=tk.X, padx=12)

        # ── Buyer / Type selection ─────────────────────────────────────────
        form = ttk.Frame(self._left, style="Panel.TFrame", padding=(12, 10))
        form.pack(fill=tk.X)

        ttk.Label(form, text="Buyer", style="Field.TLabel").grid(
            row=0, column=0, sticky="w", pady=2)
        self._buyer_var = tk.StringVar(value=self._buyer)
        self._buyer_entry = ttk.Entry(form, textvariable=self._buyer_var, width=16)
        self._buyer_entry.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        ttk.Label(form, text="Type", style="Field.TLabel").grid(
            row=1, column=0, sticky="w", pady=2)
        self._type_var = tk.StringVar(value=self._order_type)
        self._type_combo = ttk.Combobox(
            form, textvariable=self._type_var, width=14,
            values=["collection", "cw", "qr", "nos"],
        )
        self._type_combo.grid(row=1, column=1, sticky="ew", padx=(6, 0))
        form.columnconfigure(1, weight=1)

        ttk.Button(form, text="Open PDF…", command=self._cmd_open_pdf).grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(8, 2))

        # ── Progress ───────────────────────────────────────────────────────
        prog_frame = ttk.Frame(self._left, style="Panel.TFrame", padding=(12, 6))
        prog_frame.pack(fill=tk.X)

        ttk.Label(prog_frame, text="Template Progress", style="Field.TLabel").pack(
            anchor="w")
        self._progress_var = tk.IntVar(value=0)
        self._progress_bar = ttk.Progressbar(
            prog_frame, variable=self._progress_var,
            maximum=100, length=220,
        )
        self._progress_bar.pack(fill=tk.X, pady=4)
        self._progress_label = ttk.Label(prog_frame, text="0/0 fields trained",
                                          style="Field.TLabel")
        self._progress_label.pack(anchor="w")

        sep2 = tk.Frame(self._left, bg=ACCENT2, height=1)
        sep2.pack(fill=tk.X, padx=12, pady=4)

        # ── Field list ─────────────────────────────────────────────────────
        ttk.Label(self._left, text="FIELDS", style="Header.TLabel",
                  padding=(12, 4, 12, 4)).pack(fill=tk.X)

        list_frame = ttk.Frame(self._left, style="Panel.TFrame")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self._field_listbox = tk.Listbox(
            list_frame,
            bg=BG_PANEL, fg=TEXT_LIGHT, selectbackground=ACCENT,
            selectforeground="white", font=("Consolas", 9),
            borderwidth=0, highlightthickness=0, activestyle="none",
        )
        self._field_listbox.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        list_scroll = tk.Scrollbar(list_frame, orient=tk.VERTICAL,
                                    command=self._field_listbox.yview)
        list_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._field_listbox.config(yscrollcommand=list_scroll.set)
        self._field_listbox.bind("<<ListboxSelect>>", self._on_field_select)

        self._populate_field_list()

        # ── Action buttons ─────────────────────────────────────────────────
        btn_frame = ttk.Frame(self._left, style="Panel.TFrame", padding=(12, 8))
        btn_frame.pack(fill=tk.X)

        ttk.Button(btn_frame, text="⏭  Next Field",
                   command=self._cmd_next_field).pack(fill=tk.X, pady=2)
        ttk.Button(btn_frame, text="↩  Undo Last Box",
                   command=self._cmd_undo).pack(fill=tk.X, pady=2)
        ttk.Button(btn_frame, text="💾  Save Template",
                   command=self._cmd_save_template).pack(fill=tk.X, pady=2)

    def _build_canvas_area(self):
        canvas_frame = ttk.Frame(self.root)
        canvas_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Toolbar
        toolbar = ttk.Frame(canvas_frame, style="Panel.TFrame", padding=(8, 4))
        toolbar.pack(fill=tk.X)

        self._status_label = tk.Label(
            toolbar, text="Open a PDF to begin training.",
            bg=BG_PANEL, fg=ACCENT, font=("Consolas", 10, "bold"),
            anchor="w",
        )
        self._status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Button(toolbar, text="−", command=self._zoom_out, width=3).pack(
            side=tk.RIGHT, padx=2)
        self._zoom_label = tk.Label(toolbar, text="100%",
                                     bg=BG_PANEL, fg=TEXT_LIGHT,
                                     font=("Consolas", 9))
        self._zoom_label.pack(side=tk.RIGHT, padx=4)
        ttk.Button(toolbar, text="+", command=self._zoom_in, width=3).pack(
            side=tk.RIGHT, padx=2)

        # Scrollable canvas
        canvas_container = tk.Frame(canvas_frame, bg=BG_CANVAS)
        canvas_container.pack(fill=tk.BOTH, expand=True)

        self._canvas = tk.Canvas(
            canvas_container, bg=BG_CANVAS,
            cursor="crosshair", highlightthickness=0,
        )
        v_scroll = tk.Scrollbar(canvas_container, orient=tk.VERTICAL,
                                 command=self._canvas.yview)
        h_scroll = tk.Scrollbar(canvas_container, orient=tk.HORIZONTAL,
                                 command=self._canvas.xview)

        self._canvas.configure(
            yscrollcommand=v_scroll.set,
            xscrollcommand=h_scroll.set,
        )

        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Mouse bindings for region drawing
        self._canvas.bind("<ButtonPress-1>",   self._on_mouse_down)
        self._canvas.bind("<B1-Motion>",        self._on_mouse_drag)
        self._canvas.bind("<ButtonRelease-1>",  self._on_mouse_up)
        self._canvas.bind("<MouseWheel>",       self._on_scroll_wheel)

        # Keyboard
        self.root.bind("<Return>", lambda e: self._cmd_confirm_region())
        self.root.bind("<Escape>", lambda e: self._cmd_cancel_region())
        self.root.bind("<plus>",   lambda e: self._zoom_in())
        self.root.bind("<minus>",  lambda e: self._zoom_out())

    def _build_bottom_bar(self):
        bottom = ttk.Frame(self.root, style="Panel.TFrame", padding=(12, 6))
        bottom.pack(side=tk.BOTTOM, fill=tk.X)

        self._ocr_result_var = tk.StringVar(value="Draw a box around a field to see its OCR text.")
        self._ocr_label = tk.Label(
            bottom,
            textvariable=self._ocr_result_var,
            bg=BG_PANEL, fg=BOX_DONE, font=("Consolas", 10),
            anchor="w", wraplength=900,
        )
        self._ocr_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Button(bottom, text="✓ Confirm Region",
                   command=self._cmd_confirm_region).pack(side=tk.RIGHT, padx=4)
        ttk.Button(bottom, text="✗ Discard",
                   command=self._cmd_cancel_region).pack(side=tk.RIGHT, padx=4)

    # ── Field list population ─────────────────────────────────────────────────

    def _populate_field_list(self, template=None):
        from po_extractor.template_store import FIELD_DEFINITIONS
        self._field_listbox.delete(0, tk.END)
        trained = set(template.trained_fields() if template else [])
        for i, (fname, label) in enumerate(FIELD_DEFINITIONS.items()):
            tick = "✓" if fname in trained else "○"
            self._field_listbox.insert(tk.END, f"  {tick} {label}")
            if fname in trained:
                self._field_listbox.itemconfig(i, fg=BOX_DONE)
        self._fields_queue = list(FIELD_DEFINITIONS.keys())

    def _update_progress(self):
        from po_extractor.template_store import FIELD_DEFINITIONS
        if not self._template:
            return
        total   = len(FIELD_DEFINITIONS)
        trained = len(self._template.trained_fields())
        pct     = int(trained / total * 100) if total else 0
        self._progress_var.set(pct)
        self._progress_label.config(text=f"{trained}/{total} fields trained")
        self._populate_field_list(self._template)

    # ── PDF loading ───────────────────────────────────────────────────────────

    def _cmd_open_pdf(self):
        path = filedialog.askopenfilename(
            title="Open PO PDF",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if path:
            self._pdf_path = path
            self._load_pdf_and_template()

    def _load_pdf_and_template(self):
        from po_extractor.pdf_renderer import PDFRenderer, TRAIN_DPI

        buyer      = self._buyer_var.get().strip()
        order_type = self._type_var.get().strip()

        if not buyer:
            messagebox.showwarning("Missing Info", "Please enter a buyer name first.")
            return
        if not self._pdf_path:
            messagebox.showwarning("No PDF", "Please open a PDF file first.")
            return

        self._buyer      = buyer
        self._order_type = order_type

        # Load or create template
        self._template = self._store.get_or_create(buyer, order_type)
        log.info("Template loaded: %s/%s", buyer, order_type)

        # Render first page
        try:
            if self._renderer:
                self._renderer.close()
            self._renderer = PDFRenderer(self._pdf_path)
            self._rendered = self._renderer.render_page(0, dpi=TRAIN_DPI)
        except Exception as exc:
            messagebox.showerror("PDF Error", str(exc))
            return

        # Draw on canvas
        self._zoom = 1.0
        self._draw_page()
        self._update_progress()

        # Start guided training
        self._current_field_idx = 0
        self._advance_field_prompt()

    def _draw_page(self):
        """Render the PDF page image onto the canvas at current zoom."""
        if not self._rendered:
            return

        from PIL import ImageTk

        w = int(self._rendered.width_px  * self._zoom)
        h = int(self._rendered.height_px * self._zoom)

        img = self._rendered.image.resize((w, h), resample=1)   # LANCZOS
        self._photo = ImageTk.PhotoImage(img)

        self._canvas.delete("all")
        self._canvas.config(scrollregion=(0, 0, w, h))
        self._canvas.create_image(0, 0, anchor=tk.NW, image=self._photo, tags="page")

        # Redraw existing confirmed boxes
        for box_info in self._drawn_boxes:
            if box_info.get("confirmed"):
                self._redraw_confirmed_box(box_info)

        self._zoom_label.config(text=f"{int(self._zoom * 100)}%")

    def _redraw_confirmed_box(self, box_info: dict):
        bx, by, bw, bh = box_info["bbox_pixel"]
        x1 = int(bx * self._zoom)
        y1 = int(by * self._zoom)
        x2 = int((bx + bw) * self._zoom)
        y2 = int((by + bh) * self._zoom)
        rect_id = self._canvas.create_rectangle(
            x1, y1, x2, y2,
            outline=BOX_DONE, width=2, dash=(4, 2),
        )
        self._canvas.create_text(
            x1 + 4, y1 + 2,
            text=box_info["field_label"][:20],
            fill=BOX_DONE, anchor=tk.NW, font=("Consolas", 7),
        )
        box_info["rect_id"] = rect_id

    # ── Guided training ───────────────────────────────────────────────────────

    def _advance_field_prompt(self):
        from po_extractor.template_store import FIELD_DEFINITIONS
        fields = list(FIELD_DEFINITIONS.keys())

        if self._current_field_idx >= len(fields):
            self._set_status("All fields trained! Save the template.")
            messagebox.showinfo(
                "Training Complete",
                f"All fields trained!\nClick 'Save Template' to finalise.\n\n"
                f"Template: {self._buyer} / {self._order_type}",
            )
            return

        fname   = fields[self._current_field_idx]
        flabel  = FIELD_DEFINITIONS[fname]
        self._active_field = fname
        self._set_status(f"DRAW BOX →  {flabel}  (Enter=confirm, Esc=skip)")

        # Highlight field in listbox
        self._field_listbox.selection_clear(0, tk.END)
        self._field_listbox.selection_set(self._current_field_idx)
        self._field_listbox.see(self._current_field_idx)

    def _cmd_next_field(self):
        """Skip current field, advance to next."""
        self._current_field_idx += 1
        self._advance_field_prompt()

    def _on_field_select(self, event):
        """User clicked a field in the list — switch to that field."""
        sel = self._field_listbox.curselection()
        if sel:
            self._current_field_idx = sel[0]
            self._advance_field_prompt()

    # ── Mouse drawing ─────────────────────────────────────────────────────────

    def _canvas_to_page(self, cx, cy) -> tuple[float, float]:
        """Convert canvas coordinates to page coordinates (accounting for zoom and scroll)."""
        px = self._canvas.canvasx(cx)
        py = self._canvas.canvasy(cy)
        return px / self._zoom, py / self._zoom

    def _on_mouse_down(self, event):
        self._start_x, self._start_y = event.x, event.y
        if self._rect_id:
            self._canvas.delete(self._rect_id)
        self._rect_id = None

    def _on_mouse_drag(self, event):
        if self._rect_id:
            self._canvas.delete(self._rect_id)
        self._rect_id = self._canvas.create_rectangle(
            self._start_x, self._start_y, event.x, event.y,
            outline=BOX_COLOR, width=2,
        )

    def _on_mouse_up(self, event):
        if not self._rendered:
            return

        # Get canvas-space coords
        x1c = min(self._start_x, event.x)
        y1c = min(self._start_y, event.y)
        x2c = max(self._start_x, event.x)
        y2c = max(self._start_y, event.y)

        if (x2c - x1c) < 5 or (y2c - y1c) < 5:
            return   # Too small — likely a click, not a drag

        # Convert to page pixel coordinates
        px1, py1 = self._canvas_to_page(x1c, y1c)
        px2, py2 = self._canvas_to_page(x2c, y2c)

        # Clamp to page bounds
        pw = self._rendered.width_px
        ph = self._rendered.height_px
        px1 = max(0, min(pw, px1))
        py1 = max(0, min(ph, py1))
        px2 = max(0, min(pw, px2))
        py2 = max(0, min(ph, py2))

        bbox_pixel = (int(px1), int(py1), int(px2 - px1), int(py2 - py1))

        # Run OCR on this region immediately
        from po_extractor.ocr_engine import BoundingBox
        bbox_obj = BoundingBox(x=int(px1), y=int(py1), w=int(px2-px1), h=int(py2-py1))
        blocks = self._ocr.extract_region(self._rendered.image, bbox_obj)
        ocr_text = " ".join(b.text for b in blocks).strip()

        self._ocr_result_var.set(
            f"OCR result: {ocr_text!r}  |  "
            f"Field: {getattr(self, '_active_field', '?')}  |  "
            "Press Enter to confirm, Esc to discard"
        )

        # Store pending region
        self._pending_region = {
            "field_name":  getattr(self, "_active_field", ""),
            "field_label": self._get_field_label(getattr(self, "_active_field", "")),
            "bbox_pixel":  bbox_pixel,
            "ocr_text":    ocr_text,
            "confirmed":   False,
        }

    def _cmd_confirm_region(self):
        """Save the pending region to the template."""
        if not hasattr(self, "_pending_region") or not self._pending_region:
            return
        if not self._template:
            messagebox.showwarning("No Template", "Open a PDF first.")
            return

        region_info = self._pending_region
        fname       = region_info["field_name"]
        if not fname:
            messagebox.showwarning("No Field", "Select a field from the list first.")
            return

        px, py, pw, ph = region_info["bbox_pixel"]
        pw_page = self._rendered.width_px
        ph_page = self._rendered.height_px

        # Normalise to 0.0–1.0
        bbox_norm = [
            px / pw_page,
            py / ph_page,
            pw / pw_page,
            ph / ph_page,
        ]

        from po_extractor.template_store import RegionRecord
        region = RegionRecord(
            page=0,
            bbox_norm=bbox_norm,
            anchor_text=region_info["ocr_text"][:50],
            trained_at=datetime.now().isoformat(sep="T", timespec="seconds"),
        )

        self._template.set_region(fname, region)

        region_info["confirmed"] = True
        self._redraw_confirmed_box(region_info)
        self._drawn_boxes.append(region_info)

        ocr_text = region_info["ocr_text"]
        self._set_status(f"Saved: {fname} = {ocr_text!r}")
        self._ocr_result_var.set(f"✓ Confirmed: {fname} = {ocr_text!r}")
        self._update_progress()

        # Advance to next field automatically
        self._current_field_idx += 1
        self._pending_region = None
        self.root.after(800, self._advance_field_prompt)

    def _cmd_cancel_region(self):
        """Discard the pending region."""
        if self._rect_id:
            self._canvas.delete(self._rect_id)
            self._rect_id = None
        self._pending_region = None
        self._ocr_result_var.set("Discarded. Draw a new box.")

    def _cmd_undo(self):
        """Remove the last confirmed box."""
        if not self._drawn_boxes:
            return
        last = self._drawn_boxes.pop()
        if last.get("rect_id"):
            self._canvas.delete(last["rect_id"])
        # Remove from template
        fname = last["field_name"]
        if self._template and fname in self._template.fields:
            ft = self._template.fields[fname]
            if ft.regions:
                ft.regions.pop()
            if not ft.regions:
                del self._template.fields[fname]
        self._update_progress()
        self._set_status(f"Undone: {last['field_label']}")

    def _cmd_save_template(self):
        if not self._template:
            messagebox.showwarning("Nothing to Save", "No template loaded.")
            return
        self._store.save(self._template)
        trained = len(self._template.trained_fields())
        messagebox.showinfo(
            "Saved",
            f"Template saved!\n\n"
            f"Buyer: {self._template.buyer}\n"
            f"Type: {self._template.order_type}\n"
            f"Fields trained: {trained}",
        )

    # ── Zoom controls ─────────────────────────────────────────────────────────

    def _zoom_in(self):
        self._zoom = min(3.0, self._zoom + 0.25)
        self._draw_page()

    def _zoom_out(self):
        self._zoom = max(0.25, self._zoom - 0.25)
        self._draw_page()

    def _zoom_fit(self):
        if not self._rendered:
            return
        canvas_w = self._canvas.winfo_width()
        self._zoom = (canvas_w - 20) / self._rendered.width_px
        self._draw_page()

    def _on_scroll_wheel(self, event):
        if event.delta > 0:
            self._canvas.yview_scroll(-1, "units")
        else:
            self._canvas.yview_scroll(1, "units")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _set_status(self, msg: str):
        self._status_label.config(text=msg)

    def _get_field_label(self, fname: str) -> str:
        from po_extractor.template_store import FIELD_DEFINITIONS
        return FIELD_DEFINITIONS.get(fname, fname)

    # ── Launch ────────────────────────────────────────────────────────────────

    def run(self):
        self.root.mainloop()
        if self._renderer:
            self._renderer.close()


# ── Standalone entry point ────────────────────────────────────────────────────

def launch_trainer(
    buyer: str = "",
    order_type: str = "collection",
    pdf_path: str = "",
    templates_dir: str = "E:/Projects/JARVIS/templates",
):
    """Launch the training UI. Can be called from JARVIS executor."""
    from po_extractor.template_store import TemplateStore
    from po_extractor.ocr_engine import OCREngine

    store  = TemplateStore(templates_dir)
    engine = OCREngine()

    ui = TrainerUI(
        template_store=store,
        ocr_engine=engine,
        buyer=buyer,
        order_type=order_type,
        pdf_path=pdf_path,
    )
    ui.run()


if __name__ == "__main__":
    launch_trainer()
