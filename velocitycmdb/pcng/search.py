#!/usr/bin/env python3
"""
Network File Search Widget with Native Algorithm Implementations
Boyer-Moore for fixed strings, Aho-Corasick for multiple patterns
Windows-compatible with no external dependencies
"""

import sys
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Set, Iterator
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict, deque

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QLineEdit, QTextEdit, QComboBox, QCheckBox,
    QTreeWidget, QTreeWidgetItem, QSplitter, QProgressBar, QTabWidget,
    QGroupBox, QSpinBox, QFileDialog, QMessageBox, QHeaderView,
    QTableWidget, QTableWidgetItem, QAbstractItemView
)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QTimer, QModelIndex
from PyQt6.QtGui import QFont, QColor, QPixmap, QIcon, QTextCursor


@dataclass
class SearchResult:
    """Container for search results"""
    file_path: str
    line_number: int
    line_content: str
    match_start: int
    match_end: int
    pattern_matched: str = ""
    context_before: List[str] = None
    context_after: List[str] = None
    file_size: int = 0
    file_modified: str = ""


class BoyerMooreSearcher:
    """Boyer–Moore–Horspool for fast fixed string searching (bad-char only)."""

    def __init__(self, pattern: str, case_sensitive: bool = True):
        self.case_sensitive = case_sensitive
        if case_sensitive:
            self.pattern = pattern
        else:
            self.pattern = pattern.lower()

        self.pattern_len = len(self.pattern)
        self.shift = self._build_shift_table()

    def _build_shift_table(self) -> Dict[str, int]:
        """Build Horspool shift table (bad-char heuristic)."""
        table = {}
        m = self.pattern_len
        i = 0
        while i < 256:
            table[chr(i)] = m
            i += 1

        # set specific shifts; last char keeps default m
        j = 0
        while j < m - 1:
            table[self.pattern[j]] = m - 1 - j
            j += 1
        return table

    def search_line(self, text: str) -> List[int]:
        if not self.case_sensitive:
            text = text.lower()

        matches = []
        m = self.pattern_len
        n = len(text)

        if m == 0:
            return matches
        if m > n:
            return matches

        i = 0
        while i <= n - m:
            k = m - 1
            while k >= 0 and self.pattern[k] == text[i + k]:
                k -= 1
            if k < 0:
                matches.append(i)
                # shift by full pattern (classic Horspool) to find next
                i += m
            else:
                c = text[i + m - 1]
                shift = self.shift.get(c, m)
                if shift < 1:
                    shift = 1
                i += shift
        return matches

    def search_file(self, file_path: str, context_lines: int = 0,
                    max_results: int = 1000) -> List[SearchResult]:
        results = []
        try:
            st = os.stat(file_path)
            file_size = st.st_size
            if file_size > 100 * 1024 * 1024:
                return results

            file_modified = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")

            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()

            line_num = 1
            total_lines = len(lines)
            while line_num <= total_lines:
                if len(results) >= max_results:
                    break

                raw = lines[line_num - 1]
                line = raw.rstrip("\n\r")
                positions = self.search_line(line)

                pos_idx = 0
                while pos_idx < len(positions):
                    pos = positions[pos_idx]

                    before = []
                    after = []

                    if context_lines > 0:
                        start_idx = line_num - 1 - context_lines
                        if start_idx < 0:
                            start_idx = 0
                        end_idx = line_num - 1
                        while start_idx < end_idx:
                            before.append(lines[start_idx].rstrip())
                            start_idx += 1

                        a_start = line_num
                        a_end = line_num + context_lines
                        if a_end > total_lines:
                            a_end = total_lines
                        idx = a_start
                        while idx < a_end:
                            after.append(lines[idx].rstrip())
                            idx += 1

                    r = SearchResult(
                        file_path=file_path,
                        line_number=line_num,
                        line_content=line,
                        match_start=pos,
                        match_end=pos + self.pattern_len,
                        pattern_matched=self.pattern if self.case_sensitive else self.pattern.lower(),
                        context_before=before,
                        context_after=after,
                        file_size=file_size,
                        file_modified=file_modified
                    )
                    results.append(r)
                    pos_idx += 1

                line_num += 1

        except (OSError, PermissionError, UnicodeDecodeError):
            pass

        return results


class AhoCorasickNode:
    """Node in Aho-Corasick automaton"""

    def __init__(self):
        self.children: Dict[str, 'AhoCorasickNode'] = {}
        self.failure: Optional['AhoCorasickNode'] = None
        self.output: List[str] = []  # Patterns that end at this node
        self.pattern_indices: List[int] = []  # Indices of patterns that end here


class AhoCorasickSearcher:
    """Aho-Corasick algorithm for multiple pattern matching"""

    def __init__(self, patterns: List[str], case_sensitive: bool = True):
        self.patterns = patterns if case_sensitive else [p.lower() for p in patterns]
        self.case_sensitive = case_sensitive
        self.root = AhoCorasickNode()

        self._build_trie()
        self._build_failure_links()

    def _build_trie(self):
        """Build the trie structure"""
        for pattern_idx, pattern in enumerate(self.patterns):
            current = self.root

            for char in pattern:
                if char not in current.children:
                    current.children[char] = AhoCorasickNode()
                current = current.children[char]

            current.output.append(pattern)
            current.pattern_indices.append(pattern_idx)

    def _build_failure_links(self):
        """Build failure links for the automaton"""
        queue = deque()

        # Initialize failure links for level 1
        for child in self.root.children.values():
            child.failure = self.root
            queue.append(child)

        # Build failure links using BFS
        while queue:
            current = queue.popleft()

            for char, child in current.children.items():
                queue.append(child)

                # Find failure link
                failure = current.failure
                while failure is not None and char not in failure.children:
                    failure = failure.failure

                if failure is not None:
                    child.failure = failure.children[char]
                else:
                    child.failure = self.root

                # Add output from failure node
                child.output.extend(child.failure.output)
                child.pattern_indices.extend(child.failure.pattern_indices)

    def search_line(self, text: str) -> List[Tuple[int, int, str, int]]:
        """Search for patterns in text, return (start, end, pattern, pattern_idx)"""
        if not self.case_sensitive:
            text = text.lower()

        matches = []
        current = self.root

        for i, char in enumerate(text):
            # Follow failure links until we find a valid transition
            while current is not None and char not in current.children:
                current = current.failure

            if current is None:
                current = self.root
                continue

            current = current.children[char]

            # Check for pattern matches
            for pattern_idx, pattern in zip(current.pattern_indices, current.output):
                start_pos = i - len(pattern) + 1
                end_pos = i + 1
                matches.append((start_pos, end_pos, pattern, pattern_idx))

        return matches

    def search_file(self, file_path: str, context_lines: int = 0,
                    max_results: int = 1000) -> List[SearchResult]:
        """Search file for multiple patterns using Aho-Corasick"""
        results = []

        try:
            file_stat = os.stat(file_path)
            file_size = file_stat.st_size
            file_modified = datetime.fromtimestamp(file_stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")

            # Skip very large files
            if file_size > 100 * 1024 * 1024:  # 100MB limit
                return results

            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()

            for line_num, line in enumerate(lines, 1):
                if len(results) >= max_results:
                    break

                line_content = line.rstrip('\n\r')
                matches = self.search_line(line_content)

                for start_pos, end_pos, pattern, pattern_idx in matches:
                    # Get context if requested
                    context_before = []
                    context_after = []

                    if context_lines > 0:
                        start_idx = max(0, line_num - 1 - context_lines)
                        end_idx = min(len(lines), line_num + context_lines)

                        context_before = [lines[i].rstrip() for i in range(start_idx, line_num - 1)]
                        context_after = [lines[i].rstrip() for i in range(line_num, end_idx)]

                    result = SearchResult(
                        file_path=file_path,
                        line_number=line_num,
                        line_content=line_content,
                        match_start=start_pos,
                        match_end=end_pos,
                        pattern_matched=pattern,
                        context_before=context_before,
                        context_after=context_after,
                        file_size=file_size,
                        file_modified=file_modified
                    )
                    results.append(result)

        except (OSError, PermissionError, UnicodeDecodeError):
            pass

        return results


class KMPSearcher:
    """Knuth-Morris-Pratt algorithm for single pattern searching"""

    def __init__(self, pattern: str, case_sensitive: bool = True):
        self.case_sensitive = case_sensitive
        if case_sensitive:
            self.pattern = pattern
        else:
            self.pattern = pattern.lower()

        self.pattern_len = len(self.pattern)
        self.lps = self._build_lps_table()

    def _build_lps_table(self) -> List[int]:
        lps = [0] * self.pattern_len
        length = 0
        i = 1
        while i < self.pattern_len:
            if self.pattern[i] == self.pattern[length]:
                length += 1
                lps[i] = length
                i += 1
            else:
                if length != 0:
                    length = lps[length - 1]
                else:
                    lps[i] = 0
                    i += 1
        return lps

    def search_line(self, text: str) -> List[int]:
        if not self.case_sensitive:
            text = text.lower()

        matches = []
        n = len(text)
        m = self.pattern_len
        i = 0
        j = 0
        while i < n:
            if j < m and self.pattern[j] == text[i]:
                i += 1
                j += 1
                if j == m:
                    matches.append(i - j)
                    j = self.lps[j - 1]
            else:
                if j != 0:
                    j = self.lps[j - 1]
                else:
                    i += 1
        return matches

    def search_file(self, file_path: str, context_lines: int = 0,
                    max_results: int = 1000) -> List[SearchResult]:
        results = []
        try:
            st = os.stat(file_path)
            file_size = st.st_size
            if file_size > 100 * 1024 * 1024:
                return results

            file_modified = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")

            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()

            total = len(lines)
            line_idx = 0
            while line_idx < total:
                if len(results) >= max_results:
                    break

                raw = lines[line_idx]
                line = raw.rstrip("\n\r")
                hits = self.search_line(line)

                k = 0
                while k < len(hits):
                    pos = hits[k]

                    before = []
                    after = []

                    if context_lines > 0:
                        s = line_idx - context_lines
                        if s < 0:
                            s = 0
                        e = line_idx
                        while s < e:
                            before.append(lines[s].rstrip())
                            s += 1

                        a_s = line_idx + 1
                        a_e = line_idx + 1 + context_lines
                        if a_e > total:
                            a_e = total
                        p = a_s
                        while p < a_e:
                            after.append(lines[p].rstrip())
                            p += 1

                    r = SearchResult(
                        file_path=file_path,
                        line_number=line_idx + 1,
                        line_content=line,
                        match_start=pos,
                        match_end=pos + self.pattern_len,
                        pattern_matched=self.pattern if self.case_sensitive else self.pattern.lower(),
                        context_before=before,
                        context_after=after,
                        file_size=file_size,
                        file_modified=file_modified
                    )
                    results.append(r)
                    k += 1

                line_idx += 1

        except (OSError, PermissionError, UnicodeDecodeError):
            pass

        return results


class ParallelSearchEngine:
    """Parallel search engine using optimized algorithms"""

    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers

    def search_files_single_pattern(self, file_paths: List[str], pattern: str,
                                    case_sensitive: bool = True, algorithm: str = 'boyer_moore',
                                    context_lines: int = 0, max_results_per_file: int = 100) -> List[SearchResult]:
        """Search files for single pattern using specified algorithm"""

        # Validate inputs
        if not pattern or not file_paths:
            return []

        try:
            if algorithm == 'boyer_moore':
                searcher = BoyerMooreSearcher(pattern, case_sensitive)
            elif algorithm == 'kmp':
                searcher = KMPSearcher(pattern, case_sensitive)
            else:
                # Default to Boyer-Moore-Horspool
                searcher = BoyerMooreSearcher(pattern, case_sensitive)
        except Exception as e:
            print(f"Error creating searcher: {e}")
            return []

        all_results = []

        # For debugging, try sequential first
        if len(file_paths) <= 5:  # Small number of files - run sequentially
            for file_path in file_paths:
                try:
                    results = searcher.search_file(file_path, context_lines, max_results_per_file)
                    all_results.extend(results)
                except Exception as e:
                    print(f"Error searching file {file_path}: {e}")
                    continue
        else:
            # Use threading for larger file sets
            try:
                with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                    future_to_file = {
                        executor.submit(searcher.search_file, file_path, context_lines, max_results_per_file): file_path
                        for file_path in file_paths
                    }

                    for future in as_completed(future_to_file):
                        try:
                            results = future.result(timeout=30)  # 30 second timeout per file
                            all_results.extend(results)
                        except Exception as e:
                            file_path = future_to_file[future]
                            print(f"Error searching file {file_path}: {e}")
                            continue
            except Exception as e:
                print(f"Threading error, falling back to sequential: {e}")
                # Fallback to sequential processing
                for file_path in file_paths:
                    try:
                        results = searcher.search_file(file_path, context_lines, max_results_per_file)
                        all_results.extend(results)
                    except Exception as e:
                        print(f"Error searching file {file_path}: {e}")
                        continue

        return all_results

    def search_files_multiple_patterns(self, file_paths: List[str], patterns: List[str],
                                       case_sensitive: bool = True, context_lines: int = 0,
                                       max_results_per_file: int = 100) -> List[SearchResult]:
        """Search files for multiple patterns using Aho-Corasick"""

        if not patterns or not file_paths:
            return []

        try:
            searcher = AhoCorasickSearcher(patterns, case_sensitive)
        except Exception as e:
            print(f"Error creating Aho-Corasick searcher: {e}")
            return []

        all_results = []

        # Similar approach - sequential for small sets, parallel for larger
        if len(file_paths) <= 5:
            for file_path in file_paths:
                try:
                    results = searcher.search_file(file_path, context_lines, max_results_per_file)
                    all_results.extend(results)
                except Exception as e:
                    print(f"Error searching file {file_path}: {e}")
                    continue
        else:
            try:
                with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                    future_to_file = {
                        executor.submit(searcher.search_file, file_path, context_lines, max_results_per_file): file_path
                        for file_path in file_paths
                    }

                    for future in as_completed(future_to_file):
                        try:
                            results = future.result(timeout=30)
                            all_results.extend(results)
                        except Exception as e:
                            file_path = future_to_file[future]
                            print(f"Error searching file {file_path}: {e}")
                            continue
            except Exception as e:
                print(f"Threading error, falling back to sequential: {e}")
                for file_path in file_paths:
                    try:
                        results = searcher.search_file(file_path, context_lines, max_results_per_file)
                        all_results.extend(results)
                    except Exception as e:
                        print(f"Error searching file {file_path}: {e}")
                        continue

        return all_results


class SearchWorkerThread(QThread):
    """Background thread for file searching with native algorithms"""

    progress_update = pyqtSignal(int, int)  # current, total
    result_found = pyqtSignal(SearchResult)
    search_complete = pyqtSignal(int)  # total results
    error_occurred = pyqtSignal(str)

    def __init__(self, file_paths: List[str], search_patterns: List[str], search_options: Dict):
        super().__init__()
        self.file_paths = file_paths
        self.search_patterns = search_patterns
        self.search_options = search_options
        self.is_cancelled = False

    def cancel(self):
        """Cancel the search operation"""
        self.is_cancelled = True

    def run(self):
        """Execute the search"""
        try:
            if self.is_cancelled:
                return

            case_sensitive = self.search_options.get('case_sensitive', False)
            context_lines = self.search_options.get('context_lines', 0)
            algorithm = self.search_options.get('algorithm', 'boyer_moore')

            search_engine = ParallelSearchEngine()

            if len(self.search_patterns) == 1:
                # Single pattern search
                results = search_engine.search_files_single_pattern(
                    self.file_paths, self.search_patterns[0],
                    case_sensitive, algorithm, context_lines
                )
            else:
                # Multiple pattern search using Aho-Corasick
                results = search_engine.search_files_multiple_patterns(
                    self.file_paths, self.search_patterns,
                    case_sensitive, context_lines
                )

            # Emit results with progress updates
            total_results = len(results)
            for i, result in enumerate(results):
                if self.is_cancelled:
                    return
                self.result_found.emit(result)
                if i % 10 == 0:  # Update progress every 10 results
                    self.progress_update.emit(i + 1, total_results)

            self.search_complete.emit(total_results)

        except Exception as e:
            self.error_occurred.emit(str(e))


class NetworkFileSearchWidget(QWidget):
    """Advanced search widget with native algorithm implementations"""

    def __init__(self, capture_root: str = "capture"):
        super().__init__()
        self.capture_root = Path(capture_root)
        self.search_thread = None
        self.search_results = []

        self.setup_ui()

    def setup_ui(self):
        """Setup the user interface"""
        layout = QVBoxLayout(self)

        # Search controls
        search_group = QGroupBox("Search Configuration")
        search_layout = QGridLayout(search_group)

        # Search pattern(s)
        search_layout.addWidget(QLabel("Search Pattern(s):"), 0, 0)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Enter search pattern(s) - use semicolon to separate multiple patterns")
        self.search_input.returnPressed.connect(self.start_search)
        search_layout.addWidget(self.search_input, 0, 1, 1, 2)

        # Algorithm selection
        search_layout.addWidget(QLabel("Algorithm:"), 1, 0)
        self.algorithm_combo = QComboBox()
        self.algorithm_combo.addItems([
            "Boyer-Moore (Fast fixed string)",
            "KMP (Knuth-Morris-Pratt)",
            "Aho-Corasick (Multiple patterns)"
        ])
        self.algorithm_combo.currentTextChanged.connect(self.algorithm_changed)
        search_layout.addWidget(self.algorithm_combo, 1, 1)

        # Search options
        self.case_sensitive_check = QCheckBox("Case Sensitive")
        search_layout.addWidget(self.case_sensitive_check, 1, 2)

        # Context lines
        search_layout.addWidget(QLabel("Context Lines:"), 2, 0)
        self.context_spin = QSpinBox()
        self.context_spin.setRange(0, 10)
        self.context_spin.setValue(1)
        search_layout.addWidget(self.context_spin, 2, 1)

        # Algorithm info
        self.algorithm_info = QLabel()
        self.algorithm_info.setWordWrap(True)
        self.algorithm_info.setStyleSheet("color: #666; font-style: italic; font-size: 10px;")
        search_layout.addWidget(self.algorithm_info, 3, 0, 1, 3)

        layout.addWidget(search_group)

        # File filters
        filter_group = QGroupBox("File Filters")
        filter_layout = QGridLayout(filter_group)

        filter_layout.addWidget(QLabel("Directory:"), 0, 0)
        self.directory_edit = QLineEdit()
        self.directory_edit.setText(str(self.capture_root))
        filter_layout.addWidget(self.directory_edit, 0, 1)

        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self.browse_directory)
        filter_layout.addWidget(browse_btn, 0, 2)

        filter_layout.addWidget(QLabel("File Extensions:"), 1, 0)
        self.extensions_edit = QLineEdit()
        self.extensions_edit.setText(".txt,.log,.cfg,.conf")
        self.extensions_edit.setPlaceholderText("e.g., .txt,.log,.cfg")
        filter_layout.addWidget(self.extensions_edit, 1, 1, 1, 2)

        layout.addWidget(filter_group)

        # Control buttons
        button_layout = QHBoxLayout()

        self.search_btn = QPushButton("Search")
        self.search_btn.clicked.connect(self.start_search)
        self.search_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; font-weight: bold; }")
        button_layout.addWidget(self.search_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel_search)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setStyleSheet("QPushButton { background-color: #f44336; color: white; font-weight: bold; }")
        button_layout.addWidget(self.cancel_btn)

        button_layout.addStretch()

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        button_layout.addWidget(self.progress_bar)

        layout.addLayout(button_layout)

        # Results area
        results_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Results table
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(6)
        self.results_table.setHorizontalHeaderLabels([
            "File", "Line", "Pattern", "Match", "Size", "Modified"
        ])
        self.results_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.results_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.results_table.itemSelectionChanged.connect(self.show_result_details)
        results_splitter.addWidget(self.results_table)

        # Details pane
        details_widget = QWidget()
        details_layout = QVBoxLayout(details_widget)

        details_layout.addWidget(QLabel("Match Details:"))
        self.details_text = QTextEdit()
        self.details_text.setFont(QFont("Consolas", 10))
        self.details_text.setReadOnly(True)
        details_layout.addWidget(self.details_text)

        results_splitter.addWidget(details_widget)
        results_splitter.setSizes([500, 300])

        layout.addWidget(results_splitter)

        # Status bar
        self.status_label = QLabel("Ready - Select algorithm and enter search pattern(s)")
        layout.addWidget(self.status_label)

        # Initialize algorithm info
        self.algorithm_changed(self.algorithm_combo.currentText())

    def algorithm_changed(self, algorithm_text: str):
        """Update algorithm information when selection changes"""
        info_text = {
            "Boyer-Moore (Fast fixed string)":
                "Optimal for fixed string searches. Skips characters when possible, fastest for single patterns.",
            "KMP (Knuth-Morris-Pratt)":
                "Efficient single pattern matching with linear time complexity. Good for patterns with repetitive structure.",
            "Aho-Corasick (Multiple patterns)":
                "Automatically selected for multiple patterns. Searches all patterns simultaneously in linear time."
        }

        self.algorithm_info.setText(info_text.get(algorithm_text, ""))

    def browse_directory(self):
        """Browse for search directory"""
        directory = QFileDialog.getExistingDirectory(self, "Select Search Directory", str(self.capture_root))
        if directory:
            self.directory_edit.setText(directory)
            self.capture_root = Path(directory)

    def get_search_files(self) -> List[str]:
        """Get list of files to search based on filters"""
        search_dir = Path(self.directory_edit.text())
        if not search_dir.exists():
            return []

        extensions = [ext.strip() for ext in self.extensions_edit.text().split(',') if ext.strip()]
        files = []

        for file_path in search_dir.rglob("*"):
            if file_path.is_file():
                if not extensions or any(file_path.suffix.lower() == ext.lower() for ext in extensions):
                    files.append(str(file_path))

        return files

    def start_search(self):
        """Start the search operation"""
        pattern_text = self.search_input.text().strip()
        if not pattern_text:
            QMessageBox.warning(self, "Search Error", "Please enter a search pattern")
            return

        # Parse patterns
        patterns = [p.strip() for p in pattern_text.split(';') if p.strip()]

        files = self.get_search_files()
        if not files:
            QMessageBox.information(self, "No Files", "No files found matching the specified criteria")
            return

        # Clear previous results
        self.search_results.clear()
        self.results_table.setRowCount(0)
        self.details_text.clear()

        # Determine algorithm
        algorithm = 'boyer_moore'  # default
        if self.algorithm_combo.currentIndex() == 1:
            algorithm = 'kmp'
        elif len(patterns) > 1:
            algorithm = 'aho_corasick'  # Force Aho-Corasick for multiple patterns

        # Setup search options
        search_options = {
            'algorithm': algorithm,
            'case_sensitive': self.case_sensitive_check.isChecked(),
            'context_lines': self.context_spin.value()
        }

        # Start search thread
        self.search_thread = SearchWorkerThread(files, patterns, search_options)
        self.search_thread.progress_update.connect(self.update_progress)
        self.search_thread.result_found.connect(self.add_search_result)
        self.search_thread.search_complete.connect(self.search_finished)
        self.search_thread.error_occurred.connect(self.search_error)

        # Update UI
        self.search_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        algorithm_name = algorithm.replace('_', '-').title()
        pattern_info = f"{len(patterns)} pattern{'s' if len(patterns) > 1 else ''}"
        self.status_label.setText(f"Searching {len(files)} files using {algorithm_name} algorithm ({pattern_info})...")

        self.search_thread.start()

    def cancel_search(self):
        """Cancel the current search"""
        if self.search_thread and self.search_thread.isRunning():
            self.search_thread.cancel()
            self.search_thread.wait(3000)

        self.search_finished(0)

    def update_progress(self, current: int, total: int):
        """Update search progress"""
        if total > 0:
            progress = int((current / total) * 100)
            self.progress_bar.setValue(progress)

    def add_search_result(self, result: SearchResult):
        """Add a search result to the table"""
        self.search_results.append(result)

        row = self.results_table.rowCount()
        self.results_table.insertRow(row)

        # File name (relative path)
        try:
            rel_path = os.path.relpath(result.file_path, self.capture_root)
        except ValueError:
            rel_path = os.path.basename(result.file_path)

        self.results_table.setItem(row, 0, QTableWidgetItem(rel_path))
        self.results_table.setItem(row, 1, QTableWidgetItem(str(result.line_number)))
        self.results_table.setItem(row, 2, QTableWidgetItem(result.pattern_matched))

        # Truncate long lines for display
        display_content = result.line_content
        if len(display_content) > 100:
            display_content = display_content[:97] + "..."
        self.results_table.setItem(row, 3, QTableWidgetItem(display_content))

        # File size
        size_str = self.format_file_size(result.file_size)
        self.results_table.setItem(row, 4, QTableWidgetItem(size_str))

        self.results_table.setItem(row, 5, QTableWidgetItem(result.file_modified))

        # Highlight the match
        if result.match_start >= 0:
            item = self.results_table.item(row, 3)
            item.setBackground(QColor(255, 255, 0, 100))  # Light yellow

    def search_finished(self, total_results: int):
        """Handle search completion"""
        self.search_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress_bar.setVisible(False)

        self.status_label.setText(f"Search complete: {total_results} results found")

        if self.search_thread:
            self.search_thread = None

    def search_error(self, error_message: str):
        """Handle search errors"""
        self.search_finished(0)
        QMessageBox.critical(self, "Search Error", f"Search failed: {error_message}")

    def show_result_details(self):
        """Show details for selected search result"""
        current_row = self.results_table.currentRow()
        if current_row < 0 or current_row >= len(self.search_results):
            return

        result = self.search_results[current_row]

        details = []
        details.append(f"File: {result.file_path}")
        details.append(f"Line: {result.line_number}")
        details.append(f"Pattern: {result.pattern_matched}")
        details.append(f"Match Position: {result.match_start}-{result.match_end}")
        details.append(f"Size: {self.format_file_size(result.file_size)}")
        details.append(f"Modified: {result.file_modified}")
        details.append("")

        # Show context
        if result.context_before:
            details.append("--- Context Before ---")
            for i, line in enumerate(result.context_before):
                line_num = result.line_number - len(result.context_before) + i
                details.append(f"{line_num:4d}: {line}")

        details.append("--- Match ---")
        line_with_highlight = result.line_content
        if result.match_start >= 0 and result.match_end > result.match_start:
            # Add visual markers around the match
            before = line_with_highlight[:result.match_start]
            match = line_with_highlight[result.match_start:result.match_end]
            after = line_with_highlight[result.match_end:]
            line_with_highlight = f"{before}>>>{match}<<<{after}"

        details.append(f"{result.line_number:4d}: {line_with_highlight}")

        if result.context_after:
            details.append("--- Context After ---")
            for i, line in enumerate(result.context_after):
                line_num = result.line_number + i + 1
                details.append(f"{line_num:4d}: {line}")

        self.details_text.setPlainText("\n".join(details))

    def format_file_size(self, size_bytes: int) -> str:
        """Format file size in human readable format"""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.1f} MB"


def main():
    """Test the search widget"""
    app = QApplication(sys.argv)

    # Create main window
    window = NetworkFileSearchWidget()
    window.setWindowTitle("Network File Search - Native Algorithms")
    window.setGeometry(100, 100, 1200, 800)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()