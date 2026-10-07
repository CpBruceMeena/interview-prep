"""Document loading module — supports PDF, HTML, TXT, Markdown."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional

from langchain_community.document_loaders import PyPDFLoader


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
        """Load all supported documents under a directory (recursively).

        Dispatches on file extension, so it works whichever concrete loader
        it is called on.
        """
        docs = []
        for file_path in sorted(Path(directory).rglob("*")):
            if file_path.is_file() and is_supported(file_path.suffix):
                try:
                    docs.extend(loader_for(str(file_path)).load(str(file_path)))
                except Exception as e:
                    print(f"⚠️ Error loading {file_path}: {e}")
        return docs


class PDFLoader(DocumentLoader):
    """Loads PDF documents page by page (pypdf via LangChain's PyPDFLoader)."""

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
            metadata={"source": path, "type": Path(path).suffix.lstrip(".")}
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
        # soup.title.string is None when <title> is empty or has child tags;
        # Chroma rejects None metadata values, so coerce to "".
        title = (soup.title.string or "") if soup.title else ""
        return [Document(
            content=content,
            source=path,
            metadata={
                "source": path,
                "title": title,
                "type": "html",
            }
        )]


_LOADERS = {
    ".pdf": PDFLoader,
    ".txt": TextFileLoader,
    ".md": TextFileLoader,
    ".html": HTMLLoader,
    ".htm": HTMLLoader,
}


def is_supported(suffix: str) -> bool:
    return suffix.lower() in _LOADERS


def loader_for(path: str) -> DocumentLoader:
    """Factory: pick the loader for a file by its extension."""
    suffix = Path(path).suffix.lower()
    if suffix not in _LOADERS:
        raise ValueError(f"Unsupported file type: {suffix or '(none)'}")
    return _LOADERS[suffix]()
