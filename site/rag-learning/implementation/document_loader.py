"""Document loading module — supports PDF, HTML, TXT, Markdown."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional

from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_core.documents import Document as LCDocument


class Document:
    """Represents a loaded document with content and metadata."""

    def __init__(self, content: str, source: str = "",
                 metadata: Optional[dict] = None):
        self.content = content
        self.source = source
        self.metadata = metadata or {}

    def __len__(self) -> int:
        return len(self.content)

    def __repr__(self) -> str:
        return f"Document(source={self.source}, len={len(self)})"


class DocumentLoader(ABC):
    """Abstract base for document loaders — follows LSP."""

    @abstractmethod
    def load(self, path: str) -> List[Document]:
        """Load a file and return a list of Document objects."""
        pass

    def load_directory(self, directory: str) -> List[Document]:
        """Load all supported documents from a directory."""
        docs = []
        path = Path(directory)
        for file_path in path.rglob("*"):
            if file_path.is_file() and self._is_supported(file_path.suffix):
                try:
                    loaded = self._get_loader(file_path.suffix).load(
                        str(file_path))
                    docs.extend(loaded)
                except Exception as e:
                    print(f"⚠️ Error loading {file_path}: {e}")
        return docs

    def _is_supported(self, suffix: str) -> bool:
        return suffix.lower() in {".pdf", ".txt", ".md", ".html", ".htm"}

    def _get_loader(self, suffix: str) -> "DocumentLoader":
        loaders = {
            ".pdf": PDFLoader,
            ".txt": TextFileLoader,
            ".md": TextFileLoader,
            ".html": HTMLLoader,
            ".htm": HTMLLoader,
        }
        loader_class = loaders.get(suffix.lower(), TextFileLoader)
        return loader_class()


class PDFLoader(DocumentLoader):
    """Loads PDF documents using PyMuPDF via LangChain."""

    def load(self, path: str) -> List[Document]:
        loader = PyPDFLoader(path)
        pages = loader.load()
        result = []
        for page in pages:
            doc = Document(
                content=page.page_content,
                source=path,
                metadata={
                    "source": path,
                    "page": page.metadata.get("page", 0),
                    "type": "pdf",
                }
            )
            result.append(doc)
        return result


class TextFileLoader(DocumentLoader):
    """Loads plain text and markdown files."""

    def load(self, path: str) -> List[Document]:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return [Document(
            content=content,
            source=path,
            metadata={"source": path, "type": path.split(".")[-1]}
        )]


class HTMLLoader(DocumentLoader):
    """Loads HTML documents, extracting main content."""

    def load(self, path: str) -> List[Document]:
        from bs4 import BeautifulSoup
        with open(path, "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f.read(), "html.parser")
        # Remove scripts and styles
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        content = soup.get_text(separator="\n", strip=True)
        title = soup.title.string if soup.title else ""
        return [Document(
            content=content,
            source=path,
            metadata={
                "source": path,
                "title": title,
                "type": "html",
            }
        )]
