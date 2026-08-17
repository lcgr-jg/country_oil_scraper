"""
Base scraper class that defines the interface for all country scrapers.

Design rationale:
- Each country scraper inherits from BaseScraper
- download() handles fetching raw files from the web
- parse() handles converting raw files into clean DataFrames
- Separation lets you re-parse cached files without re-downloading
- Metadata (source, download timestamp, units) travels with the data

Layer split (see ARCHITECTURE.md for full detail):
- Scraper: download + parse one raw file → source-native tidy DataFrame
- Processor: load / upsert / save + canonical mapping (product_canonical, category)
- Update script: CLI that wires scraper + processor

Production pipelines use processors; BaseScraper.run() is a prototyping shortcut.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from datetime import datetime
import logging
import pandas as pd
import yaml

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """
    Abstract base for country-specific petroleum data scrapers.
    
    Subclasses must implement:
        - download(dataset_name) -> Path to raw file
        - parse(dataset_name, raw_path) -> pd.DataFrame
    
    The base class provides:
        - Config loading from sources.yaml
        - Directory management (raw/processed)
        - Metadata tracking
        - save_processed() for writing parquet with metadata
    """
    
    def __init__(self, country: str, data_dir: str = "data"):
        self.country = country
        self.data_dir = Path(data_dir)
        self.raw_dir = self.data_dir / "raw" / country
        self.processed_dir = self.data_dir / "processed" / country
        
        # Create dirs
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        
        # Load config
        self.config = self._load_config()
    
    def _load_config(self) -> dict:
        """Load the country's source configuration from sources.yaml."""
        config_path = Path(__file__).parent.parent / "config" / "sources.yaml"
        if not config_path.exists():
            # Fallback: look relative to cwd
            config_path = Path("config") / "sources.yaml"
        
        with open(config_path, encoding="utf-8") as f:
            all_config = yaml.safe_load(f)
        
        country_config = all_config.get(self.country)
        if country_config is None:
            raise ValueError(
                f"No config found for country '{self.country}'. "
                f"Available: {list(all_config.keys())}"
            )
        return country_config
    
    @property
    def datasets(self) -> list[str]:
        """List available dataset names for this country."""
        return list(self.config.get("datasets", {}).keys())
    
    def get_dataset_config(self, dataset_name: str) -> dict:
        """Get config for a specific dataset."""
        ds = self.config.get("datasets", {}).get(dataset_name)
        if ds is None:
            raise ValueError(
                f"Unknown dataset '{dataset_name}' for {self.country}. "
                f"Available: {self.datasets}"
            )
        return ds
    
    @abstractmethod
    def download(self, dataset_name: str) -> Path:
        """
        Download raw data file for the given dataset.
        
        Returns:
            Path to the downloaded raw file.
        """
        ...
    
    @abstractmethod
    def parse(self, dataset_name: str, raw_path: Path) -> pd.DataFrame:
        """
        Parse a raw downloaded file into a clean DataFrame.
        
        The returned DataFrame should have:
            - Clean column names (lowercase, underscored)
            - Proper dtypes (dates as datetime, numbers as float)
            - A 'source' column with the dataset name
            - A 'country' column
        
        Returns:
            Cleaned pandas DataFrame.
        """
        ...
    
    def run(self, dataset_name: str, force_download: bool = False) -> pd.DataFrame:
        """
        Full pipeline: download (if needed) -> parse -> save processed.
        
        Args:
            dataset_name: Which dataset to fetch/parse
            force_download: If True, re-download even if raw file exists
        
        Returns:
            Cleaned DataFrame
        """
        logger.info(f"[{self.country}] Running pipeline for: {dataset_name}")
        
        # Download
        raw_path = self.download(dataset_name)
        logger.info(f"  Raw file: {raw_path}")
        
        # Parse
        df = self.parse(dataset_name, raw_path)
        logger.info(f"  Parsed: {len(df)} rows, {len(df.columns)} columns")
        
        # Save processed
        self.save_processed(dataset_name, df)
        
        return df
    
    def save_processed(self, dataset_name: str, df: pd.DataFrame) -> Path:
        """Save cleaned DataFrame as parquet with timestamp in filename."""
        timestamp = datetime.now().strftime("%Y%m%d")
        out_path = self.processed_dir / f"{dataset_name}_{timestamp}.parquet"
        df.to_parquet(out_path, index=False)
        logger.info(f"  Saved processed: {out_path}")
        return out_path
    
    def __repr__(self):
        return (
            f"<{self.__class__.__name__} country='{self.country}' "
            f"datasets={self.datasets}>"
        )
