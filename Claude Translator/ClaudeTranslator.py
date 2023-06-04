import requests
import time
import anthropic
import json
import tkinter as tk
import threading
import os
import sys
import configparser
import ast
import queue
import tiktoken
from tkinter import font, Menu
from tkinter import font
from tkinter import filedialog
from tkinter import ttk
from collections import OrderedDict

# Global variables
auto_paste = False
auto_translate = False
dark_mode = False
translated_dict = OrderedDict()
copied_text_queue = queue.Queue()
old_clipboard = ""
history = []
dictionary = []
history_window_open = False
ask_win_open = False
sub_window_font = {"family": "Yu Gothic", "size": 10}

def check_prompt_file(prompt_logfile):
    try:
        with open(prompt_logfile, "r", encoding="utf-8") as f:
            prompt_text = f.read()
    except FileNotFoundError:
        prompt_logfile = ""
        save_settings("prompt_logfile", prompt_logfile)
        prompt_text = "You are an AI translator assistant. You will help translate text and dialogues to English and if provided, use context as a reference. Try to keep the emotions, dialects, and meanings from the original text and convey them in the translation as much as possible. Do not make them sound bland like a robot. Only reply the translation and nothing else. Do not write detailed explanations."
    return prompt_logfile, prompt_text
    
def check_log_file(translation_logfile):
    try:
        with open(translation_logfile, "r", encoding="utf-8") as f:
                log_translations = True
    except FileNotFoundError:
        translation_logfile = ""
        log_translations = False
        save_settings("translation_logfile", translation_logfile)
        save_settings("log_translations", log_translations)
    return translation_logfile, log_translations

def load_settings():
    # Load settings from cfg file
    settings_data = {}
    config = configparser.ConfigParser()
    try:
        config.read('settings.cfg')
        if 'Settings' in config.sections():
            settings_data = dict(config.items('Settings'))
    except FileNotFoundError:
        pass
    return settings_data

def save_settings(key, value):
    # Save settings to the cfg file
    settings_data = load_settings()
    settings_data[key] = value
    config = configparser.ConfigParser()
    config['Settings'] = settings_data
    with open('settings.cfg', 'w') as settings_file:
        config.write(settings_file)

def update_display(display, text):
    display.config(state=tk.NORMAL)
    if not streaming:
        display.delete(1.0, tk.END)
    display.insert(tk.END, text)
    display.config(state=tk.DISABLED)
    if append_paste or streaming:
        display.see(tk.END)

def toggle_line_breaks():
    global remove_line_breaks
    remove_line_breaks = not remove_line_breaks
    save_settings("remove_line_breaks", remove_line_breaks)
    
def remove_older_lines(textbox, max_tokens):
    raw_text = textbox.get(1.0, tk.END)
    parsed_text = parse_text(raw_text)
    num_tokens = num_tokens_from_messages(parsed_text)
    #print(f"Token Counter:{num_tokens} tokens counted\nmax_tokens:{max_tokens}\n")
    if num_tokens > max_tokens:
        lines = raw_text.split('\n')
        while num_tokens_from_messages(parse_text('\n'.join(lines))) > max_tokens:
            lines.pop(0)
        new_text = '\n'.join(lines)
        new_text = new_text.replace('\n\n\n', '\n\n')
        textbox.delete(1.0, tk.END)
        textbox.insert(1.0, new_text)

def parse_text(text):
    return [
        {
            "content": line.strip(),
        }
        for line in text.split('\n')
        if line.strip()
    ]

def translate_text(transl_textbox, sysprom, rawtext, histories, stream, ask=False):
    global translated_dict, history_table, history

    prompt_text = sysprom.get(1.0, tk.END).strip()
    text_to_translate = rawtext.get(1.0, tk.END).strip()
    
    #stop_sequences = ["\n\nAssistant:", "\n\nHuman:", "\n\nSystem:"]
    messages = f"\n\nHuman: {prompt_text}"
    if dictionary:
        messages += f"\n\nDictionary: {dictionary}"
    if ask:
        for message in history[-(context_size//2):]:
            messages += f"\n\n{message['role']}: {message['content']}"
    for message in histories[-(context_size//2):]:
        messages += f"\n\n{message['role']}: {message['content']}"
    messages += f"\n\nHuman: {text_to_translate}\n\nAssistant:"
    parsed_messages = parse_text(messages)
    prompt_tokens = num_tokens_from_messages(parsed_messages)
    if prompt_tokens > context_size and history:
        #print(f"Token exceeded:{prompt_tokens} tokens counted. Cutting Histories...\n\n")
        history.pop(0)
        history.pop(0)
        translate_text(transl_textbox, sysprom, rawtext, histories, stream, ask)
        return
        
    c = anthropic.Client(api_key=anth_api_key)
    lencount = len(messages)
    #print(f"{messages}\n\n")
    #print(f"Token Counter:{prompt_tokens} tokens counted\nLen count={lencount}\n")
        
    try:
        response = c.completion_stream(
            prompt=messages,
            model=model,
            max_tokens_to_sample=max_response_length,
            temperature=temperature,
            stream=stream,
            top_k=top_k,
            top_p=top_p,
        )
    except Exception as e:
        root.after(0, create_error_window, f"{e}")
        return
    
    wrote = 0
    transl_textbox.config(state=tk.NORMAL)
    transl_textbox.delete(1.0, tk.END)
    for data in response:
        data_message = data["completion"][wrote:]
        wrote = len(data["completion"])
        if data_message:
            update_display(transl_textbox, data_message)
    translated_text = transl_textbox.get(1.0, tk.END).strip()
        
    translated_dict[text_to_translate] = translated_text
    histories.append({"role": "Human", "content": text_to_translate})
    histories.append({"role": "Assistant", "content": translated_text})
    if not ask:
        with open("chat_history.json", "w", encoding="utf-8") as json_file:
            json.dump(histories, json_file, ensure_ascii=False)
        
    if history_window_open and not ask:
        for item in history_table.get_children():
            history_table.delete(item)
        prev_untranslated_text = ""
        prev_translated_text = ""
        for i, item in enumerate(histories):
            if item["role"] == "Human":
                untranslated_text = item["content"]
                if prev_untranslated_text:
                    history_table.insert("", "end", values=(prev_untranslated_text, prev_translated_text))
                prev_untranslated_text = untranslated_text
            else:
                translated_text = item["content"]
                prev_translated_text = translated_text 
        history_table.insert("", "end", values=(prev_untranslated_text, prev_translated_text))

    if log_translations and not ask:
        with open(translation_logfile, "a", encoding="utf-8") as f:
            if multilang:
                f.write(f"{text_to_translate}\n\n")
            f.write(f"{translated_text}\n\n")

def num_tokens_from_messages(messages):
    # Temporarily using tiktoken
    # because i can't find Anthropic's
    # token counter on the docs
    encoding = tiktoken.encoding_for_model("gpt-4-0314")
    tokens_per_message = 3
    tokens_per_name = 1
    num_tokens = 0
    for message in messages:
        num_tokens += tokens_per_message
        for key, value in message.items():
            num_tokens += len(encoding.encode(value))
            if key == "name":
                num_tokens += tokens_per_name
    num_tokens += 3
    return num_tokens

def clipboard_monitor():
    global old_clipboard

    while True:
        if auto_paste:
            try:
                new_clipboard = root.clipboard_get()
            except tk.TclError:
                continue

            if new_clipboard != old_clipboard:
                to_translate = apply_substitutions(new_clipboard, substitutions)
                
                if apply_pre:
                    to_translate = prefix + to_translate
                if apply_suf:
                    to_translate = to_translate + suffix

                if remove_line_breaks:
                    to_translate = to_translate.replace('\n', '').replace('\r', '')
            
                untranslated_textbox.edit_separator()
                untranslated_textbox.config(autoseparator=False)
                
                if append_paste:
                    untranslated_textbox.insert(tk.END, to_translate + '\n\n')
                    remove_older_lines(untranslated_textbox, append_limit)
                    untranslated_textbox.see(tk.END)
                else:
                    untranslated_textbox.delete(1.0, tk.END)
                    untranslated_textbox.insert(tk.END, to_translate)
                    
                untranslated_textbox.config(autoseparator=True)
                untranslated_textbox.edit_separator()
                
                old_clipboard = new_clipboard
                copied_text_queue.put(new_clipboard)
           
        #for thread in threading.enumerate(): 
        #    print(thread.name)
        time.sleep(1)

def translation_worker():
    global translated_dict
    
    while True:
        if auto_translate and not copied_text_queue.empty():
            while not copied_text_queue.empty():
                last_queue = copied_text_queue.get()
            
            text_to_translate = untranslated_textbox.get(1.0, tk.END).strip()
            if text_to_translate in translated_dict:
                translated_text = translated_dict[text_to_translate]
                translated_dict.move_to_end(text_to_translate)
                update_display(translated_textbox, translated_text)
            else:
                translate_text(translated_textbox, prompt_textbox, untranslated_textbox, history, streaming)
                
        time.sleep(1)

def save():
    global prompt_logfile, prompt_text
    prompt_text = prompt_textbox.get(1.0, tk.END).strip()
    try:
        with open(prompt_logfile, "w", encoding="utf-8") as f:
            f.write(prompt_text)
    except FileNotFoundError as e:
        save_as()

def save_as():
    global prompt_logfile, prompt_text
    prompt_text = prompt_textbox.get(1.0, tk.END).strip()
    new_prompt_logfile = filedialog.asksaveasfilename(initialdir=os.getcwd(),
                                                title="Save Prompt As",
                                                defaultextension=".txt", 
                                                filetypes=(("Text files", ".txt"), ("All files", ".")))
    if not new_prompt_logfile:
        return
    prompt_logfile = new_prompt_logfile
    save_settings("prompt_logfile", prompt_logfile)
    with open(prompt_logfile, "w", encoding="utf-8") as f:
        f.write(prompt_text)

def load_prompt():
    global prompt_logfile, prompt_text
    new_prompt_logfile = filedialog.askopenfilename(initialdir=os.getcwd(),
                                                title="Load Prompt",
                                                defaultextension=".txt", 
                                                filetypes=(("Text files", ".txt"), ("All files", ".")))
    if not new_prompt_logfile:
        return
    prompt_logfile = new_prompt_logfile
    save_settings("prompt_logfile", prompt_logfile)
    with open(prompt_logfile, "r", encoding="utf-8") as f:
        prompt_text = f.read()
        prompt_textbox.delete(1.0, tk.END)
        prompt_textbox.insert(1.0, prompt_text)

def toggle_append():
    global append_paste
    append_paste = not append_paste
    if append_paste:
        untranslated_textbox.insert(tk.END, '\n\n')
    save_settings("append_paste", append_paste)

def toggle_streaming():
    global streaming
    streaming = not streaming
    save_settings("streaming", streaming)

def streambind(event):
    streaming_var.set(not streaming_var.get())
    toggle_streaming()

def set_always_on_top():
    root.attributes("-topmost", always_on_top_var.get())
    save_settings("always_on_top", always_on_top_var.get())

def set_aon(event):
    always_on_top_var.set(not always_on_top_var.get())
    set_always_on_top()

def increase_opacity():
    opacity = root.attributes("-alpha")
    opacity = min(opacity + 0.1, 1.0)
    root.attributes("-alpha", opacity)
    save_settings("window_opacity", opacity)

def decrease_opacity():
    opacity = root.attributes("-alpha")
    opacity = max(opacity - 0.1, 0.1)
    root.attributes("-alpha", opacity)
    save_settings("window_opacity", opacity)

def toggle_dark_mode():
    global dark_mode, last_color
    if not untranslated_textbox.cget("foreground") == "black" and not untranslated_textbox.cget("foreground") == "white":
        last_color = untranslated_textbox.cget("foreground")
    dark_mode = not dark_mode
    
    bg_color = "black" if dark_mode else "white"
    fg_color = "white" if dark_mode else last_color
    
    translated_textbox.configure(bg=bg_color, fg=fg_color)
    untranslated_textbox.configure(bg=bg_color, fg=fg_color)
    prompt_textbox.configure(bg=bg_color, fg=fg_color)
    root.configure(bg=bg_color)
    menu_bar.configure(bg=bg_color, fg=fg_color)

def darkbind(event):
    dark_mode_var.set(not dark_mode_var.get())
    toggle_dark_mode()

def multilingual():
    global multilang
    multilang = not multilang
    save_settings("log_multilingual", multilang)
    multilang_var.set(multilang)

def toggle_logging():
    global log_translations, translation_logfile
    log_translations = not log_translations
    try:
        with open(translation_logfile, "r", encoding="utf-8") as f:
            save_settings("log_translations", log_translations)
            log_translations_var.set(log_translations)
    except FileNotFoundError:
        toggle_log = True
        save_log(toggle_log)

def save_log(toggle_log=False):
    global log_translations, translation_logfile
    new_translation_logfile = filedialog.asksaveasfilename(initialdir=os.getcwd(),
                                                title="Save Log As",
                                                defaultextension=".txt", 
                                                filetypes=(("Text files", ".txt"), ("All files", ".")))
    if not new_translation_logfile:
        if toggle_log:
            log_translations = not log_translations
            log_translations_var.set(log_translations)
        return
    translation_logfile = new_translation_logfile
    save_settings("log_translations", log_translations)
    save_settings("translation_logfile", translation_logfile)
    try:
        with open(translation_logfile, "w", encoding="utf-8") as f:
            translations = translated_textbox.get(1.0, tk.END).strip()
            f.write(f"{translations}\n\n")
            #if multilang:
            #    f.write(f"{text_to_translate}\n")
    except FileNotFoundError:
        pass

def change_log():
    global translation_logfile
    new_translation_logfile = filedialog.askopenfilename(initialdir=os.getcwd(),
                                                title="Load Log As",
                                                defaultextension=".txt", 
                                                filetypes=(("Text files", ".txt"), ("All files", ".")))
    if not new_translation_logfile:
        return
    translation_logfile = new_translation_logfile
    save_settings("translation_logfile", translation_logfile)

def create_error_window(message):
    error_window = tk.Toplevel()
    error_window.transient(root)
    error_window.title("Error")
    error_window.config(bg='white')
    error_window.iconbitmap(icon_path)
    
    main_frame = ttk.Frame(error_window)
    main_frame.place(relx=0.5, rely=0.5, anchor='center')
    
    error_textbox = tk.Text(error_window, wrap="word", width=50, height=5, font='Helvetica 10 bold', bg="whitesmoke")
    error_textbox.insert(tk.END, message)
    error_textbox.configure(state="disabled")
    error_textbox.pack(padx=10, pady=10)
    
    error_window.resizable(False, False)
    
    close_button = ttk.Button(error_window, text="Close", command=error_window.destroy)
    close_button.pack(side=tk.RIGHT, pady=5, padx=5)
    error_window.grab_set()

def font_window():
    global current_font
    current_font = {
        "family": font.Font(font=untranslated_textbox["font"]).actual("family"),
        "size": font.Font(font=untranslated_textbox["font"]).actual("size"),
        "color": untranslated_textbox.cget("foreground"),
        "bold": font.Font(font=untranslated_textbox["font"]).actual("weight") == "bold",
        "italic": font.Font(font=untranslated_textbox["font"]).actual("slant") == "italic"
    }

    font_window = tk.Toplevel()
    font_window.transient(root) 
    font_window.title("Font Settings")
    font_window.geometry("170x170")
    font_window.config(bg='white')
    font_window.iconbitmap(icon_path)
    
    main_frame = ttk.Frame(font_window)
    main_frame.place(relx=0.5, rely=0.5, anchor='center')
    
    font_family = tk.StringVar()
    font_family_label = ttk.Label(font_window, text="Font")
    font_family_label.pack()
    font_family_entry = ttk.Entry(font_window, textvariable=font_family)
    font_family_entry.insert(0, current_font["family"])
    font_family_entry.pack()

    font_size = tk.StringVar()
    font_size_label = ttk.Label(font_window, text="Font Size")
    font_size_label.pack()
    font_size_entry = ttk.Entry(font_window, textvariable=font_size)
    font_size_entry.insert(0, current_font["size"])
    font_size_entry.pack()

    font_color = tk.StringVar()
    font_color_label = ttk.Label(font_window, text="Font Color")
    font_color_label.pack()
    font_color_entry = ttk.Entry(font_window, textvariable=font_color)
    font_color_entry.insert(0, current_font["color"])
    font_color_entry.pack()
    
    italic_button = tk.Button(
        font_window,
        text="I",
        command=lambda: toggle_style("italic", italic_button), 
        relief=tk.SUNKEN if current_font["italic"] else tk.RAISED,
        fg="white", bg="grey"
    )
    italic_button.pack(side=tk.LEFT, padx=5)
    bold_button = tk.Button(
        font_window,
        text="B",
        command=lambda: toggle_style("bold", bold_button),
        relief=tk.SUNKEN if current_font["bold"] else tk.RAISED,
        fg="white", bg="grey"
    )
    bold_button.pack(side=tk.LEFT, padx=5)
    
    font_window.resizable(False, False)
    
    def toggle_style(style, button):
        global current_font
        current_font[style] = not current_font[style]
        button.config(relief=tk.SUNKEN if current_font[style] else tk.RAISED)

    def apply_changes():
        global current_font, last_color
        new_font_family = font_family.get() or current_font["family"]
        new_font_size = font_size.get() or current_font["size"]
        new_font_color = font_color.get() or current_font["color"]
        new_font_bold = "bold" if current_font["bold"] else "normal"
        new_font_italic = "italic" if current_font["italic"] else "roman"
        last_color = new_font_color
        current_font = {
            "family": new_font_family,
            "size": new_font_size, 
            "color": new_font_color,
            "bold": new_font_bold,
            "italic": new_font_italic
        }

        untranslated_textbox.configure(
            font=(current_font["family"], current_font["size"], current_font["bold"], current_font["italic"]),
            fg=current_font["color"]
        )
        translated_textbox.configure(
            font=(current_font["family"], current_font["size"], current_font["bold"], current_font["italic"]),
            fg=current_font["color"]
        )
        prompt_textbox.configure(
            font=(current_font["family"], current_font["size"], current_font["bold"], current_font["italic"]),
            fg=current_font["color"]
        )
        save_settings("font_settings", str(current_font))
        font_window.destroy()
        
    apply_button = ttk.Button(font_window, text="Apply", command=apply_changes)
    apply_button.pack(side=tk.BOTTOM, pady=10)
    font_window.grab_set()

def set_parameters():
    global max_response_length, temperature, context_size, top_k, top_p

    def save_parameters():
        global max_response_length, temperature, context_size, top_k, top_p

        max_response_length = int(max_response_length_var.get()) if max_response_length_var.get() else max_response_length
        context_size = int(context_size_var.get()) if context_size_var.get() else context_size
        temperature = float(temperature_var.get()) if temperature_var.get() else temperature
        top_k = float(top_k_var.get()) if top_k_var.get() else top_k
        top_p = float(top_p_var.get()) if top_p_var.get() else top_p
        
        save_settings("context_size", context_size)
        save_settings("max_response_length", max_response_length)
        save_settings("temperature", temperature)
        save_settings("top_k", top_k)
        save_settings("top_p", top_p)
        
        params_window.destroy()
        
    params_window = tk.Toplevel()
    params_window.transient(root)
    params_window.title("Parameters")
    params_window.geometry("160x430")
    params_window.config(bg='white')
    params_window.iconbitmap(icon_path)
    
    main_frame = ttk.Frame(params_window)
    main_frame.place(relx=0.5, rely=0.5, anchor='center')
 
    temperature_var = tk.StringVar(value=temperature)
    temperature_label = ttk.Label(params_window, text="Temperature:")
    temperature_label.pack(side=tk.TOP, pady=(20, 5))
    temperature_entry = ttk.Entry(params_window, textvariable=temperature_var, width=15)
    temperature_entry.pack(side=tk.TOP, padx=10)

    context_size_var = tk.StringVar(value=context_size)
    context_size_label = ttk.Label(params_window, text="Context Size:")
    context_size_label.pack(side=tk.TOP, pady=(20, 5))
    context_size_entry = ttk.Entry(params_window, textvariable=context_size_var, width=15)
    context_size_entry.pack(side=tk.TOP, padx=10)

    max_response_length_var = tk.StringVar(value=max_response_length)
    max_response_length_label = ttk.Label(params_window, text="Max Response Length:")
    max_response_length_label.pack(side=tk.TOP, pady=(20, 5))
    max_response_length_entry = ttk.Entry(params_window, textvariable=max_response_length_var, width=15)
    max_response_length_entry.pack(side=tk.TOP, padx=10)
    
    top_k_var = tk.StringVar(value=top_k)
    top_k_label = ttk.Label(params_window, text="top_k:")
    top_k_label.pack(side=tk.TOP, pady=(20, 5))
    top_k_entry = ttk.Entry(params_window, textvariable=top_k_var, width=15)
    top_k_entry.pack(side=tk.TOP, padx=10)

    top_p_var = tk.StringVar(value=top_p)
    top_p_label = ttk.Label(params_window, text="top_p:")
    top_p_label.pack(side=tk.TOP, pady=(20, 5))
    top_p_entry = ttk.Entry(params_window, textvariable=top_p_var, width=15)
    top_p_entry.pack(side=tk.TOP, padx=10)
    
    params_window.resizable(False, False)
    
    cancel_button = ttk.Button(params_window, text="Cancel", command=lambda: params_window.destroy())
    cancel_button.pack(side=tk.BOTTOM, pady=10)
    save_button = ttk.Button(params_window, text="Save", command=save_parameters)
    save_button.pack(side=tk.BOTTOM, pady=10)
    params_window.grab_set()

def set_api():
    global model
    api_window = tk.Toplevel()
    api_window.transient(root)
    api_window.title("Anthropic API")
    api_window.geometry("350x150")
    api_window.config(bg='white')
    api_window.iconbitmap(icon_path)
    
    main_frame = ttk.Frame(api_window)
    main_frame.place(relx=0.5, rely=0.5, anchor='center')

    api_key = tk.StringVar()
    api_key_label = ttk.Label(api_window, text="API Key:")
    api_key_label.pack(side=tk.TOP, pady=5)
    api_key_entry = ttk.Entry(api_window, textvariable=api_key, width=50, show="*")
    api_key_entry.insert(0, anth_api_key)
    api_key_entry.pack(side=tk.TOP, padx=10)
    
    model_var = tk.StringVar(value=model)
    model_label = ttk.Label(api_window, text="Model:")
    model_label.place(relx=0.05, rely=0.7, anchor="sw")
    model_options = ["claude-v1", "claude-instant-v1", "claude-instant-v1.1", "claude-v1-100k", "claude-instant-v1-100k", "claude-instant-v1.1-100k", "claude-v1.2", "claude-v1.3", "claude-v1.3-100k"]
    model_entry = ttk.OptionMenu(api_window, model_var, model, *model_options)
    model_entry.place(relx=0.05, rely=0.9, anchor="sw")
    
    api_window.resizable(False, False)

    def save_api_settings():
        global model
        anth_api_key = api_key.get()
        model = model_var.get()
        
        save_settings("anth_api_key", api_key.get())
        save_settings("model", model)
        api_window.destroy()
    
    save_button = ttk.Button(api_window, text="Save", command=save_api_settings)
    save_button.place(relx=0.95, rely=0.9, anchor="se")
    
    api_window.grab_set()

def sub_win():
    
    def add_substitution(original_entry, replacement_entry, substitution_table):
        original_text = original_entry.get()
        replacement_text = replacement_entry.get()
        if original_text:
            substitution_table.insert("", "end", values=(original_text, replacement_text))
            original_entry.delete(0, "end")
            replacement_entry.delete(0, "end")

    def update_substitution(substitution_table, original_entry, replacement_entry):
        selected_item = substitution_table.selection()
        if selected_item:
            original_text = original_entry.get()
            replacement_text = replacement_entry.get()
            if original_text:
                substitution_table.item(selected_item[0], values=(original_text, replacement_text))
                original_entry.delete(0, "end")
                replacement_entry.delete(0, "end")
                substitution_table.selection_remove(selected_item)

    def delete_substitution(substitution_table, event=None):
        selected_items = substitution_table.selection()
        for item in selected_items:
            substitution_table.delete(item)

    def save_substitutions(substitution_table, filename="substitutions.json"):
        global substitutions
        substitutions = []
        for item in substitution_table.get_children():
            original_text, replacement_text = substitution_table.item(item)["values"]
            substitutions.append((original_text, replacement_text))
        
        with open(filename, "w") as f:
            json.dump(substitutions, f)
        sub_window.destroy()

    def handle_selection(substitution_table, original_entry, replacement_entry):
        nonlocal selected_item
        if selected_item and substitution_table.selection() == selected_item:
            substitution_table.selection_remove(selected_item)
        selected_item = substitution_table.selection()
        if selected_item:
            original_text, replacement_text = substitution_table.item(selected_item[0])["values"]
            original_entry.delete(0, "end")
            original_entry.insert(0, original_text)
            replacement_entry.delete(0, "end")
            replacement_entry.insert(0, replacement_text)

    sub_window = tk.Toplevel(root)
    sub_window.transient(root)
    sub_window.title("Substitutions")
    sub_window.geometry("440x420")
    sub_window.iconbitmap(icon_path)
    selected_item = None
    
    main_frame = ttk.Frame(sub_window)
    main_frame.place(relx=0.5, rely=0.5, anchor='center')

    input_frame = tk.LabelFrame(sub_window, text="Add Substitutions")
    input_frame.pack(pady=10, padx=10, fill="x")

    original_label = tk.Label(input_frame, text="Original Text:")
    original_label.grid(row=0, column=0, padx=5, pady=5)

    original_entry = ttk.Entry(input_frame, width=20, font=sub_window_font)
    original_entry.grid(row=0, column=1, padx=5, pady=5)

    replacement_label = tk.Label(input_frame, text="Replacement Text:")
    replacement_label.grid(row=1, column=0, padx=5, pady=5)

    replacement_entry = ttk.Entry(input_frame, width=20, font=sub_window_font)
    replacement_entry.grid(row=1, column=1, padx=5, pady=5)

    add_button = ttk.Button(
        input_frame,
        text="Add",
        command=lambda: update_substitution(substitution_table, original_entry, replacement_entry) if substitution_table.selection() else add_substitution(original_entry, replacement_entry, substitution_table)
    )
    add_button.grid(row=1, column=2, padx=5)

    table_frame = ttk.Frame(sub_window)
    table_frame.pack(pady=10, padx=10, fill="both", expand=True)

    columns = ("Original Text", "Replacement Text")
    substitution_table = ttk.Treeview(table_frame, columns=columns, show="headings")
    substitution_table.bind("<<TreeviewSelect>>", lambda event: handle_selection(substitution_table, original_entry, replacement_entry))
    substitution_table.bind("<Delete>", lambda event: delete_substitution(substitution_table, event))
    substitution_table.bind("<Control-a>", lambda event: substitution_table.selection_set(substitution_table.get_children()))

    for col in columns:
        substitution_table.heading(col, text=col)
        substitution_table.column(col, stretch=True, anchor="center")
    
    for original, replacement in substitutions:
        substitution_table.insert("", "end", values=(original, replacement))
    
    scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=substitution_table.yview)
    scrollbar.pack(side="right", fill="y")

    substitution_table.configure(yscrollcommand=scrollbar.set)
    substitution_table.pack(side="left", fill="both", expand=True)
    
    button_frame = tk.Frame(sub_window)
    button_frame.pack(pady=10, padx=10, fill="x")

    delete_button = ttk.Button(button_frame, text="Delete", command=lambda: delete_substitution(substitution_table))
    delete_button.pack(side="left", padx=5)
        
    save_button = ttk.Button(button_frame, text="Save", command=lambda: save_substitutions(substitution_table))
    save_button.pack(side="right", padx=5)
    cancel_button = ttk.Button(button_frame, text="Cancel", command=lambda: sub_window.destroy())
    cancel_button.pack(side="right", padx=5)

    sub_window.resizable(False, False)
    sub_window.grab_set()

def apply_substitutions(text, substitutions):
    for original, replacement in substitutions:
        text = text.replace(original, str(replacement))
    return text

def load_substitutions(filename="substitutions.json"):
    if os.path.exists(filename):
        with open(filename, "r") as f:
            return json.load(f)
    return []

def dictwin():

    def add_dictionary(original_entry, dictionary_entry, dictionary_table):
        original_text = original_entry.get()
        dictionary_text = dictionary_entry.get()
        if original_text and dictionary_text:
            dictionary_table.insert("", "end", values=(original_text, dictionary_text))
            original_entry.delete(0, "end")
            dictionary_entry.delete(0, "end")

    def update_dictionary(dictionary_table, original_entry, dictionary_entry):
        selected_item = dictionary_table.selection()
        if selected_item:
            original_text = original_entry.get()
            dictionary_text = dictionary_entry.get()
            if original_text and dictionary_text:
                dictionary_table.item(selected_item[0], values=(original_text, dictionary_text))
                dictionary_table.selection_remove(selected_item)
                original_entry.delete(0, "end")
                dictionary_entry.delete(0, "end")

    def delete_dictionary(dictionary_table, event=None):
        selected_items = dictionary_table.selection()
        for item in selected_items:
            dictionary_table.delete(item)

    def save_dictionary(dictionary_table, filename="dictionary.json"):
        global dictionary
        dictionary = []
        for item in dictionary_table.get_children():
            original_text, dictionary_text = dictionary_table.item(item)["values"]
            dictionary.append([original_text, dictionary_text])
            
        with open(filename, "w") as f:
            json.dump(dictionary, f)
        dict_win.destroy()
        
    def handle_selection(dictionary_table, original_entry, dictionary_entry):
        nonlocal selected_item
        if selected_item and dictionary_table.selection() == selected_item:
            dictionary_table.selection_remove(selected_item)
        selected_item = dictionary_table.selection()
        if selected_item:
            original_text, dictionary_text = dictionary_table.item(selected_item[0])["values"]
            original_entry.delete(0, "end")
            original_entry.insert(0, original_text)
            dictionary_entry.delete(0, "end")
            dictionary_entry.insert(0, dictionary_text)
    
    dict_win = tk.Toplevel(root)
    dict_win.transient(root)
    dict_win.title("Dictionary")
    dict_win.geometry("440x420")
    dict_win.iconbitmap(icon_path)
    selected_item = None

    input_frame = tk.LabelFrame(dict_win, text="Add Dictionary")
    input_frame.pack(pady=10, padx=10, fill="x")

    original_label = tk.Label(input_frame, text="Word/Phrase:")
    original_label.grid(row=0, column=0, padx=5, pady=5)

    original_entry = ttk.Entry(input_frame, width=20, font=sub_window_font)
    original_entry.grid(row=0, column=1, padx=5, pady=5)
    
    dictionary_label = tk.Label(input_frame, text="Meaning:")
    dictionary_label.grid(row=1, column=0, padx=5, pady=5)

    dictionary_entry = ttk.Entry(input_frame, width=20, font=sub_window_font)
    dictionary_entry.grid(row=1, column=1, padx=5, pady=5)

    add_button = ttk.Button(
        input_frame,
        text="Add",
        command=lambda: update_dictionary(dictionary_table, original_entry, dictionary_entry) if dictionary_table.selection() else add_dictionary(original_entry, dictionary_entry, dictionary_table)
    )
    add_button.grid(row=1, column=2, padx=5)

    dictable_frame = ttk.Frame(dict_win)
    dictable_frame.pack(pady=10, padx=10, fill="both", expand=True)

    columns = ("Words", "Meanings")
    dictionary_table = ttk.Treeview(dictable_frame, columns=columns, show="headings")
    dictionary_table.bind("<<TreeviewSelect>>", lambda event: handle_selection(dictionary_table, original_entry, dictionary_entry))
    dictionary_table.bind("<Delete>", lambda event: delete_dictionary(dictionary_table, event))
    dictionary_table.bind("<Control-a>", lambda event: dictionary_table.selection_set(dictionary_table.get_children()))

    for col in columns:
        dictionary_table.heading(col, text=col)
        dictionary_table.column(col, stretch=True, anchor="center")
    
    for original, meaning in dictionary:
        dictionary_table.insert("", "end", values=(original, meaning))
    
    scrollbar = ttk.Scrollbar(dictable_frame, orient="vertical", command=dictionary_table.yview)
    scrollbar.pack(side="right", fill="y")

    dictionary_table.configure(yscrollcommand=scrollbar.set)
    dictionary_table.pack(side="left", fill="both", expand=True)
    
    button_frame = tk.Frame(dict_win)
    button_frame.pack(pady=10, padx=10, fill="x")

    delete_button = ttk.Button(button_frame, text="Delete", command=lambda: delete_dictionary(dictionary_table))
    delete_button.pack(side="left", padx=5)

    save_button = ttk.Button(button_frame, text="Save", command=lambda: save_dictionary(dictionary_table))
    save_button.pack(side="right", padx=5)
    cancel_button = ttk.Button(button_frame, text="Cancel", command=lambda: dict_win.destroy())
    cancel_button.pack(side="right", padx=5)

    dict_win.resizable(False, False)
    dict_win.grab_set()

def load_dict(filename="dictionary.json"):
    if os.path.exists(filename):
        with open(filename, "r") as f:
            return json.load(f)
    return []

def history_window():
    global history_window_open, history_table
    history_window_open = True
    
    def save_history(history_table):
        global history, history_window_open
        history = []
        for item in history_table.get_children():
            untranslated_text, translated_text = history_table.item(item)["values"]
            history.append({"role": "Human", "content": untranslated_text})
            history.append({"role": "Assistant", "content": translated_text})

        with open("chat_history.json", "w", encoding="utf-8") as json_file:
            json.dump(history, json_file, ensure_ascii=False)
        history_window_open = False
        history_window.destroy()

    def history_selection(history_table, raw_text, translation_box):
        selected_item = history_table.selection()
        if selected_item:
           untranslated_text, translated_text = history_table.item(selected_item[0])["values"]
           raw_text.config(state=tk.NORMAL)
           raw_text.delete(1.0, tk.END)
           raw_text.insert(1.0, untranslated_text)
           raw_text.config(state=tk.DISABLED)
           translation_box.config(state=tk.NORMAL)
           translation_box.delete(1.0, tk.END)
           translation_box.insert(1.0, translated_text)
           translation_box.config(state=tk.DISABLED)

    def delete_history(history_table, event=None):
        selected_items = history_table.selection()
        for item in selected_items:
            history_table.delete(item)
    
    def on_history_close(): 
        global history_window_open
        history_window_open = False
        history_window.destroy()

    history_window = tk.Toplevel(root)
    history_window.transient(root)
    history_window.title("History")
    history_window.geometry("600x500")
    history_window.iconbitmap(icon_path)
    
    main_frame = ttk.Frame(history_window)
    main_frame.place(relx=0.5, rely=0.5, anchor='center')

    table_frame = ttk.Frame(history_window)
    table_frame.pack(pady=10, padx=10, fill="both", expand=True)

    columns = ("Raw Text", "Translated Text")
    history_table = ttk.Treeview(table_frame, columns=columns, show="headings")
    history_table.bind("<<TreeviewSelect>>", lambda event: history_selection(history_table, raw_text, translation_box))
    history_table.bind("<Delete>", lambda event: delete_history(history_table, event))
    history_table.bind("<Control-a>", lambda event: history_table.selection_set(history_table.get_children()))

    for col in columns:
        history_table.heading(col, text=col)
        history_table.column(col, stretch=True, anchor="center")
    
    prev_untranslated_text = ""
    prev_translated_text = ""
    for i, item in enumerate(history):
        if item["role"] == "Human":
            untranslated_text = item["content"]
            if prev_untranslated_text:
                history_table.insert("", "end", values=(prev_untranslated_text, prev_translated_text))
            prev_untranslated_text = untranslated_text
        else:
            translated_text = item["content"]
            prev_translated_text = translated_text 

    history_table.insert("", "end", values=(prev_untranslated_text, prev_translated_text)) 
        
    scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=history_table.yview)
    scrollbar.pack(side="right", fill="y")

    history_table.configure(yscrollcommand=scrollbar.set)
    history_table.pack(side="left", fill="both", expand=True)
    
    raw_text = tk.Text(history_window, wrap="word", width=64, height=5, font=sub_window_font, state=tk.DISABLED)
    raw_text.pack()
    
    translation_box = tk.Text(history_window, wrap="word", width=64, height=5, font=sub_window_font, state=tk.DISABLED)
    translation_box.pack()

    his_button_frame = tk.Frame(history_window)
    his_button_frame.pack(pady=10, padx=10, fill="x")
    
    delete_button = ttk.Button(his_button_frame, text="Delete", command=lambda: delete_history(history_table))
    delete_button.pack(side="left", padx=5)
    
    history_window.protocol("WM_DELETE_WINDOW", on_history_close)
    save_button = ttk.Button(his_button_frame, text="Save", command=lambda: save_history(history_table))
    save_button.pack(side="right", padx=5)
    cancel_button = ttk.Button(his_button_frame, text="Cancel", command=on_history_close)
    cancel_button.pack(side="right", padx=5)

    history_window.resizable(False, False)
    history_window.grab_set()
    
def load_history():
    try:
        with open("chat_history.json", "r", encoding="utf-8") as json_file:
            loaded_history = json.load(json_file)
    except Exception as e:
        loaded_history = []
    return loaded_history

def create_buttons_window():
    global buttons_window, apply_pre, apply_suf, ask_win, ask_win_open
    
    buttons_window = tk.Toplevel(root)
    buttons_window.title("Buttons")
    buttons_window.iconbitmap(icon_path)
    
    def regenerate_text():
        global history
        if len(history) == 2:
            history.pop()
        else:
            history.pop()
            history.pop()
        translate_text(translated_textbox, prompt_textbox, untranslated_textbox, history, streaming)
    
    def toggle_auto_paste():
        global auto_paste
        auto_paste = not auto_paste
        auto_paste_button.config(relief=tk.SUNKEN if auto_paste else tk.RAISED)

    def toggle_auto_translate():
        global auto_translate
        auto_translate = not auto_translate
        auto_translate_button.config(relief=tk.SUNKEN if auto_translate else tk.RAISED)
        
    def buttons_on_top(event=None):
        if event:
            buttons_on_top_var.set(not buttons_on_top_var.get())
        if buttons_window.attributes("-topmost"):
            buttons_window.attributes("-topmost", 0)
        else:
            buttons_window.attributes("-topmost", 1)

    def toggle_frameless(event=None):
        if event:
            buttons_frameless_var.set(not buttons_frameless_var.get())
        if buttons_window.overrideredirect():
            buttons_window.overrideredirect(False)
        else:
            buttons_window.overrideredirect(True)
    
    def appre():
        global apply_pre
        apply_pre = not apply_pre
        auto_pre_button.config(relief=tk.SUNKEN if apply_pre else tk.RAISED)
        apply_two_button.config(relief=tk.SUNKEN if apply_suf and apply_pre else tk.RAISED)
        save_settings("apply_pre", apply_pre)

    def apsuf():
        global apply_suf
        apply_suf = not apply_suf
        auto_suf_button.config(relief=tk.SUNKEN if apply_suf else tk.RAISED)
        apply_two_button.config(relief=tk.SUNKEN if apply_suf and apply_pre else tk.RAISED)
        save_settings("apply_suf", apply_suf)
    
    def apply_two():
        if not apply_pre and apply_suf:
            appre()
        elif apply_pre and not apply_suf:
            apsuf()
        elif not apply_pre and not apply_suf:
            appre()
            apsuf()
        else:
            appre()
            apsuf()
        apply_two_button.config(relief=tk.SUNKEN if apply_suf and apply_pre else tk.RAISED)

    translate_button = tk.Button(buttons_window, text="Translate", command=lambda: threading.Thread(target=translate_text, args=(translated_textbox, prompt_textbox, untranslated_textbox, history, streaming)).start(), fg="white", bg="grey")
    translate_button.grid(row=0, column=1)
    regenerate_button = tk.Button(buttons_window, text="Regenerate", command=lambda: threading.Thread(target=regenerate_text).start(), fg="white", bg="grey")
    regenerate_button.grid(row=0, column=2)
    ask_button = tk.Button(buttons_window, text="Ask", command=lambda: ask_window() if not ask_win_open else ask_win.deiconify(), fg="white", bg="grey")
    ask_button.grid(row=0, column=3)
    auto_paste_button = tk.Button(buttons_window, text="Auto Paste", command=toggle_auto_paste, relief=tk.RAISED, fg="white", bg="grey")
    auto_paste_button.grid(row=0, column=4)
    apply_two_button = tk.Button(buttons_window, text="Apply:", command=apply_two, relief=tk.RAISED if not apply_pre and not apply_suf else tk.SUNKEN, fg="white", bg="grey")
    apply_two_button.grid(row=0, column=5)
    auto_pre_button = tk.Button(buttons_window, text="Prefix", command=appre, relief=tk.RAISED if not apply_pre else tk.SUNKEN, fg="white", bg="grey")
    auto_pre_button.grid(row=0, column=6)
    auto_suf_button = tk.Button(buttons_window, text="Suffix", command=apsuf, relief=tk.RAISED if not apply_suf else tk.SUNKEN, fg="white", bg="grey")
    auto_suf_button.grid(row=0, column=7)    
    auto_translate_button = tk.Button(buttons_window, text="Auto Translate", command=toggle_auto_translate, relief=tk.RAISED, fg="white", bg="grey")
    auto_translate_button.grid(row=0, column=8)
    plus_button = tk.Button(buttons_window, text="+", command=lambda: buttons_menu.post(plus_button.winfo_rootx(), plus_button.winfo_rooty() + plus_button.winfo_height()), fg="white", bg="grey")
    plus_button.grid(row=0, column=9)
    
    buttons_on_top_var = tk.BooleanVar(value=False)
    buttons_frameless_var = tk.BooleanVar(value=False)
    
    buttons_menu = tk.Menu(buttons_window, tearoff=False)
    buttons_menu.add_checkbutton(label="Borderless", variable=buttons_frameless_var, command=toggle_frameless, accelerator="Alt-Shift-F")
    buttons_menu.add_checkbutton(label="Always on top", variable=buttons_on_top_var, command=buttons_on_top, accelerator="Alt-Shift-A")
    buttons_menu.add_separator()
    buttons_menu.add_command(label="Increase opacity", command=lambda: buttons_window.attributes("-alpha", min(buttons_window.attributes("-alpha") + 0.1, 1.0)), accelerator="Alt-(=)")
    buttons_menu.add_command(label="Increase opacity            ", command=lambda: buttons_window.attributes("-alpha", max(buttons_window.attributes("-alpha") - 0.1, 0.1)), accelerator="Alt-(-)")
    
    buttons_window.bind("<Alt-Shift-A>", buttons_on_top)
    buttons_window.bind("<Alt-Shift-F>", toggle_frameless)
    buttons_window.bind("<Alt-=>", lambda event: buttons_window.attributes("-alpha", min(buttons_window.attributes("-alpha") + 0.1, 1.0)))
    buttons_window.bind("<Alt-minus>", lambda event: buttons_window.attributes("-alpha", max(buttons_window.attributes("-alpha") - 0.1, 0.1)))
    buttons_window.resizable(False, False)
    buttons_window.protocol("WM_DELETE_WINDOW", lambda: buttons_window.withdraw())
        
def frameless_bind(event=None):
    if event:
        borderless_var.set(not borderless_var.get())
    if root.overrideredirect():
        root.overrideredirect(False)
    else:
        root.overrideredirect(True)
    save_settings("borderless", borderless_var.get())

def toggle_orientation():
    current_orient = paned_window.cget("orient")
    new_orient = "horizontal" if current_orient == "vertical" else "vertical"
    save_settings("orient", new_orient)
    paned_window.configure(orient=new_orient)

def auto_settings():
    global prefix, suffix, append_limit
    
    def save_auto_settings():
        global prefix, suffix, append_limit
        append_limit = int(append_limit_var.get()) if append_limit_var.get() else append_limit
        prefix = prefix_entry.get()
        suffix = suffix_entry.get()
 
        save_settings("append_limit", append_limit)
        data = {'prefix': prefix, 'suffix': suffix}
        with open('prefix_suffix.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
            
        fix_window.destroy()

    fix_window = tk.Toplevel(root)
    fix_window.transient(root) 
    fix_window.title("Auto Settings")
    fix_window.geometry("200x180")
    fix_window.config(bg='white')
    fix_window.iconbitmap(icon_path)
    
    main_frame = ttk.Frame(fix_window)
    main_frame.place(relx=0.5, rely=0.5, anchor='center')

    prefix_label = ttk.Label(fix_window, text="Prefix:")
    prefix_label.pack()
    prefix_entry = ttk.Entry(fix_window, font=sub_window_font)
    prefix_entry.pack()

    suffix_label = ttk.Label(fix_window, text="Suffix:")
    suffix_label.pack()
    suffix_entry = ttk.Entry(fix_window, font=sub_window_font)
    suffix_entry.pack()
    
    append_limit_var = tk.StringVar(value=append_limit)
    append_limit_label = ttk.Label(fix_window, text="Append Limit:")
    append_limit_label.pack()
    append_limit_entry = ttk.Entry(fix_window, textvariable=append_limit_var, width=15)
    append_limit_entry.pack()

    save_button = ttk.Button(fix_window, text="Save", command=save_auto_settings)
    save_button.pack(side="right", padx=10, pady=5)
    cancel_button = ttk.Button(fix_window, text="Cancel", command=lambda: fix_window.destroy())
    cancel_button.pack(side="left", padx=10, pady=5)

    prefix_entry.insert(tk.END, prefix)
    suffix_entry.insert(tk.END, suffix)
    fix_window.resizable(False, False)
    fix_window.grab_set()

def load_prefix_suffix():
    try:
        with open('prefix_suffix.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data['prefix'], data['suffix']
    except FileNotFoundError:
        return "", ""

def update_old_clipboard(event=None):
    global old_clipboard
    selected_text = root.clipboard_get()
    old_clipboard = selected_text

def toggle_menu():
    if root.config('menu')[-1]:
        root.config(menu="")
    else:
        root.config(menu=menu_bar)
    save_settings("frame", toolbar_var.get())

def toggle_menubind(event):
    toolbar_var.set(not toolbar_var.get())
    toggle_menu()

def ask_window():
    global ask_win, ask_win_open
    ask_win_open = True
    ask_history = []
    
    def clear_ask():
        nonlocal ask_history
        ask_history = []
    
    ask_win = tk.Toplevel(root)
    ask_win.title("Ask")
    ask_win.geometry("400x370")
    ask_win.iconbitmap(icon_path)
    ask_win.resizable(False, False)
    ask_win.protocol("WM_DELETE_WINDOW", lambda: ask_win.withdraw())
    ask_win.attributes("-topmost", always_on_top_var.get())
    always_on_top_var.trace("w", lambda name, index, mode, sv=ask_win: sv.attributes("-topmost", always_on_top_var.get()))

    input_frame = tk.LabelFrame(ask_win, text="System Prompt")
    input_frame.pack(pady=10, padx=10, fill="x")
    
    asksysprompt = f"You are an AI translator assistant. You will help translate text to English while trying to keep the emotions, dialects, and meanings from the original text and convey them in the translation as much as possible. Do not make them sound bland like a robot."
    ask_system = EntryEx(input_frame, width=40, height=2, font=sub_window_font)
    ask_system.insert(tk.END, asksysprompt)
    ask_system.grid(row=0, column=1, padx=5, pady=5)

    input_frame2 = tk.LabelFrame(ask_win, text="Prompt")
    input_frame2.pack(pady=10, padx=10, fill="x")

    ask_prompt = EntryEx(input_frame2, width=40, height=2, font=sub_window_font)
    ask_prompt.grid(row=0, column=1, padx=5, pady=5)
    
    answer_frame = tk.LabelFrame(ask_win, text="Answer")
    answer_frame.pack(pady=10, padx=10, fill="x")

    answer_text = EntryEx(answer_frame, height=5, width=40, font=sub_window_font)
    answer_text.config(state=tk.DISABLED)
    answer_text.grid(row=0, column=1, padx=5, pady=5)

    asking_button = ttk.Button(ask_win, text="Ask", 
        command=lambda: threading.Thread(target=translate_text, args=(answer_text, ask_system, ask_prompt, ask_history, streaming, True)).start() if ask_prompt.get(1.0, tk.END).strip() != "" else None
    )
    asking_button.pack(side="right", padx=5)

    cancel_button = ttk.Button(ask_win, text="Cancel", command=lambda: ask_win.withdraw())
    cancel_button.pack(side="right", padx=5)
    
    clear_ask_button = ttk.Button(ask_win, text="Clear Ask History", command=clear_ask)
    clear_ask_button.pack(side="left", padx=5)

class Theme:
    def __init__(self, root):
        self.root = root
        self.style = ttk.Style()
        self.style.theme_use('clam')
        self.style.configure('TFrame', background='white', relief='flat')
        self.style.configure('TLabel', background='white', foreground='black')
        self.style.configure('TButton', background='grey', foreground='white', relief='flat')
        self.style.configure('TEntry', background='white', foreground='black', relief='flat')
        self.style.configure('TCombobox', background='white', foreground='black', relief='flat')
        self.style.configure('TCheckbutton', background='white', foreground='black', relief='flat')
        self.style.configure('TRadiobutton', background='white', foreground='black', relief='flat')
        self.style.configure('TNotebook', background='white', foreground='black', relief='flat')
        self.style.configure('TNotebook.Tab', background='white', foreground='black')
        self.style.configure("Treeview", font=sub_window_font)

class EntryEx(tk.Text):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config(wrap="word", undo=True, autoseparators=True, maxundo=-1)
        self.menu = tk.Menu(self, tearoff=False)
        self.menu.add_command(label="Undo", command=self.popup_undo, accelerator="Ctrl-Z")
        self.menu.add_command(label="Redo", command=self.popup_redo, accelerator="Ctrl-Y")
        self.menu.add_separator()
        self.menu.add_command(label="Copy", command=self.popup_copy, accelerator="Ctrl-C")
        self.menu.add_command(label="Cut", command=self.popup_cut, accelerator="Ctrl-X")
        self.menu.add_command(label="Paste", command=self.popup_paste, accelerator="Ctrl-V")
        self.menu.add_separator()
        self.menu.add_checkbutton(label="Always on top", variable=always_on_top_var, command=set_always_on_top, accelerator="Alt-A")
        self.menu.add_checkbutton(label="Borderless", variable=borderless_var, command=frameless_bind, accelerator="Ctrl-F")
        self.menu.add_checkbutton(label="Hide Toolbar", variable=toolbar_var, command=toggle_menu, accelerator="Ctrl-T")
        self.menu.add_separator()
        self.menu.add_command(label="Increase opacity", command=increase_opacity, accelerator="Ctrl-(=)")
        self.menu.add_command(label="Decrease opacity", command=decrease_opacity, accelerator="Ctrl-(-)")
        self.bind("<Button-3>", self.display_popup)

    def display_popup(self, event):
        self.menu.post(event.x_root, event.y_root)
        
    def popup_undo(self):
        self.event_generate("<<Undo>>")
        
    def popup_redo(self):
        self.event_generate("<<Redo>>")

    def popup_copy(self):
        self.event_generate("<<Copy>>")
        update_old_clipboard()

    def popup_cut(self):
        self.event_generate("<<Cut>>")
        update_old_clipboard()

    def popup_paste(self):
        self.event_generate("<<Paste>>")

root = tk.Tk()
root.title("Claude Translator")
root.geometry("400x200")

icon_path = "icon.ico"
if getattr(sys, 'frozen', False):
    icon_path = os.path.join(sys._MEIPASS, "icon.ico")

root.iconbitmap(icon_path)

settings_data = load_settings()
substitutions = load_substitutions()
dictionary = load_dict()

anth_api_key = settings_data.get("anth_api_key", "")
prompt_logfile = settings_data.get("prompt_logfile", "")
always_on_top = settings_data.get("always_on_top", "False").lower() == "true"
window_opacity = float(settings_data.get("window_opacity", 1.0))
log_translations = settings_data.get("log_translations", "False").lower() == "true"
multilang = settings_data.get("log_multilingual", "False").lower() == "true"
translation_logfile = settings_data.get("translation_logfile", "")
remove_line_breaks = settings_data.get("remove_line_breaks", "False").lower() == "true"
apply_pre = settings_data.get("apply_pre", "False").lower() == "true"
apply_suf = settings_data.get("apply_suf", "False").lower() == "true"
append_paste = settings_data.get("append_paste", "False").lower() == "true"
orient = settings_data.get("orient", "vertical")
append_limit = int(settings_data.get("append_limit", 1000))
borderless = settings_data.get("borderless", "False").lower() == "true"
toolbar = settings_data.get("frame", "False").lower() == "true"

model = settings_data.get("model", "claude-v1")
temperature = float(settings_data.get("temperature", 0.5))
context_size = int(settings_data.get("context_size", 3000))
max_response_length = int(settings_data.get("max_response_length", 1000))
top_k = float(settings_data.get("top_k", -1))
top_p = float(settings_data.get("top_p", -1))
streaming = settings_data.get("streaming", "False").lower() == "true"

prompt_logfile, prompt_text = check_prompt_file(prompt_logfile)
prefix, suffix = load_prefix_suffix()
history = load_history()

font_settings_str = settings_data.get("font_settings", "")
if font_settings_str:
    font_settings = ast.literal_eval(font_settings_str)
else:
    font_settings = {"family": "Yu Gothic", "size": 12, "color": "black", "bold": "normal", "italic": "roman"}
if log_translations:
    translation_logfile, log_translations = check_log_file(translation_logfile)
    
menu_bar = Menu(root)
root.config(menu=menu_bar)

borderless_var = tk.BooleanVar(value=borderless)
toolbar_var = tk.BooleanVar(value=toolbar)
always_on_top_var = tk.BooleanVar(value=always_on_top)
dark_mode_var = tk.BooleanVar(value=False)
streaming_var = tk.BooleanVar(value=streaming)
log_translations_var = tk.BooleanVar(value=log_translations)
multilang_var = tk.BooleanVar(value=multilang)
append_paste_var = tk.BooleanVar(value=append_paste)
line_breaks_var = tk.BooleanVar(value=remove_line_breaks)

anthropic_menu = Menu(menu_bar, tearoff=0)
menu_bar.add_cascade(label="Anthropic", menu=anthropic_menu)
anthropic_menu.add_command(label="API", command=set_api)
anthropic_menu.add_command(label="Parameters", command=set_parameters)
anthropic_menu.add_checkbutton(label="Streaming", variable=streaming_var, command=toggle_streaming, accelerator="Alt-S")
anthropic_menu.add_command(label="History", command=history_window)
anthropic_menu.add_command(label="Dictionary", command=dictwin)

options_menu = Menu(menu_bar, tearoff=0)
menu_bar.add_cascade(label="Options", menu=options_menu)
options_menu.add_command(label="Restore Buttons", command=lambda: buttons_window.deiconify(), accelerator="Alt-B")
options_menu.add_command(label="Change Orientation", command=toggle_orientation, accelerator="Alt-W")
options_menu.add_checkbutton(label="Always on top", variable=always_on_top_var, command=set_always_on_top, accelerator="Alt-A")
options_menu.add_checkbutton(label="Borderless", variable=borderless_var, command=frameless_bind, accelerator="Ctrl-F")
options_menu.add_checkbutton(label="Hide Toolbar", variable=toolbar_var, command=toggle_menu, accelerator="Ctrl-T")
options_menu.add_separator()
options_menu.add_command(label="Increase opacity", command=increase_opacity, accelerator="Ctrl-(=)")
options_menu.add_command(label="Decrease opacity", command=decrease_opacity, accelerator="Ctrl-(-)")
options_menu.add_separator()
options_menu.add_command(label="Font Settings", command=font_window)
options_menu.add_checkbutton(label="Dark Mode", variable=dark_mode_var, command=toggle_dark_mode, accelerator="Ctrl-B")

prompt_menu = Menu(menu_bar, tearoff=0)
menu_bar.add_cascade(label="Prompt", menu=prompt_menu)
prompt_menu.add_command(label="Save", command=save, accelerator="Ctrl-S")
prompt_menu.add_command(label="Save As", command=save_as, accelerator="Ctrl-Shift+S")
prompt_menu.add_command(label="Load", command=load_prompt, accelerator="Ctrl-L")

log_menu = Menu(menu_bar, tearoff=0)
menu_bar.add_cascade(label="Log", menu=log_menu)
log_menu.add_checkbutton(label="Enable", variable=log_translations_var, command=toggle_logging)
log_menu.add_checkbutton(label="Log Raw Text", variable=multilang_var, command=multilingual)
log_menu.add_command(label="Set Log File", command=save_log)
log_menu.add_command(label="Change Log File", command=change_log)

paste_menu = Menu(menu_bar, tearoff=0)
menu_bar.add_cascade(label="Auto Paste", menu=paste_menu)
paste_menu.add_command(label="Settings", command=auto_settings)
paste_menu.add_command(label="Substitutions", command=sub_win)
paste_menu.add_separator()
paste_menu.add_checkbutton(label="Append Text", variable=append_paste_var, command=toggle_append)
paste_menu.add_checkbutton(label="Remove Line Breaks", variable=line_breaks_var, command=toggle_line_breaks)

paned_window = tk.PanedWindow(root, sashrelief="flat", sashwidth=5, orient=orient)
paned_window.pack(expand=True, fill="both")
untranslated_textbox = EntryEx(paned_window)
translated_textbox = EntryEx(paned_window)
translated_textbox.config(state=tk.DISABLED, undo=False, autoseparators=False)
prompt_textbox = EntryEx(paned_window)
paned_window.add(untranslated_textbox)
paned_window.add(translated_textbox)
paned_window.add(prompt_textbox)

update_display(prompt_textbox, prompt_text)
prompt_textbox.config(state=tk.NORMAL)

root.bind_all("<Alt-a>", set_aon)
root.bind_all("<Alt-s>", streambind)
root.bind_all("<Control-t>", toggle_menubind)
root.bind_all("<Control-f>", frameless_bind)
root.bind_all("<Control-b>", darkbind)
root.bind_all("<Control-=>", lambda event: increase_opacity())
root.bind_all("<Control-minus>", lambda event: decrease_opacity())
root.bind_all("<Alt-w>", lambda event: toggle_orientation())
root.bind_all("<Alt-b>", lambda event: buttons_window.deiconify())
paned_window.bind_all("<Control-c>", update_old_clipboard)
paned_window.bind_all("<Control-x>", update_old_clipboard)
prompt_textbox.bind("<Control-s>", lambda event: save())
prompt_textbox.bind("<KeyPress-S>", lambda event: save_as(), add="+Ctrl+Shift")
prompt_textbox.bind("<Control-l>", lambda event: load_prompt())

def set_window_settings():
    global font_settings
    root.attributes("-topmost", always_on_top)
    root.attributes("-alpha", window_opacity)
    if borderless:
        root.overrideredirect(True)
    if toolbar:
        root.config(menu="")
    untranslated_textbox.configure(
            font=(font_settings["family"], font_settings["size"], font_settings["bold"], font_settings["italic"]),
            fg=font_settings["color"]
        )
    translated_textbox.configure(
            font=(font_settings["family"], font_settings["size"], font_settings["bold"], font_settings["italic"]),
            fg=font_settings["color"]
        )
    prompt_textbox.configure(
            font=(font_settings["family"], font_settings["size"], font_settings["bold"], font_settings["italic"]),
            fg=font_settings["color"]
        )

last_color = font_settings["color"]
set_window_settings()
theme = Theme(root)

if __name__ == "__main__":
    exe_mode = getattr(sys, 'frozen', False)
    if exe_mode:
        sys.stderr = open("error_log.txt", "w")
    clipmon_thread = threading.Thread(target=clipboard_monitor)
    clipmon_thread.start()
    transworker_thread = threading.Thread(target=translation_worker)
    transworker_thread.start()
    
    def on_closing():
        os._exit(0)
    
    create_buttons_window()
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()
