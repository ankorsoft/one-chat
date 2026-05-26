"""
ClamAV antivirus client for file scanning.
Scans uploaded files before storage.
"""
import logging
from typing import Tuple
import socket
import asyncio

from clamd import ClamdNetworkSocket

from backend.infrastructure.config import get_settings

logger = logging.getLogger(__name__)


class ClamAVClient:
    """
    Async ClamAV client for virus scanning.
    
    Features:
    - Stream-based scanning for large files
    - Multiple scan result types
    - Connection pooling
    """
    
    _instance: "ClamAVClient" = None
    
    def __new__(cls) -> "ClamAVClient":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        settings = get_settings()
        
        self.host = settings.clamav.host
        self.port = settings.clamav.port
        self.timeout = settings.clamav.timeout
        
        self._client = None
        self._initialized = True
    
    def _get_client(self) -> ClamdNetworkSocket:
        """Get or create the ClamAV client."""
        if self._client is None:
            self._client = ClamdNetworkSocket(
                host=self.host,
                port=self.port,
                timeout=self.timeout,
            )
        return self._client
    
    async def scan_file(self, file_bytes: bytes) -> Tuple[bool, str]:
        """
        Scan file bytes for viruses.
        
        Args:
            file_bytes: File content to scan
            
        Returns:
            Tuple of (is_clean, signature_or_error)
            - is_clean: True if no threats detected
            - signature: Virus signature if found, or error message
        """
        try:
            client = self._get_client()
            
            # Use stream scanning for memory efficiency
            # Run in executor to avoid blocking
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: client.instream(file_bytes)
            )
            
            status = result.get('stream', ('', ''))[0]
            
            if status == 'OK':
                logger.debug("File scan clean")
                return True, ""
            elif status == 'FOUND':
                signature = result.get('stream', ('', ''))[1]
                logger.warning(f"Virus detected: {signature}")
                return False, signature
            else:
                logger.error(f"Scan error: {status}")
                return False, f"Scan error: {status}"
                
        except Exception as e:
            logger.error(f"ClamAV scan failed: {e}")
            # Fail open or closed based on config
            # For security, we fail closed (assume infected)
            return False, f"Scanner error: {str(e)}"
    
    async def scan_files(self, files: list[bytes]) -> list[Tuple[bool, str]]:
        """
        Scan multiple files.
        
        Args:
            files: List of file bytes to scan
            
        Returns:
            List of (is_clean, signature) tuples
        """
        results = []
        for file_bytes in files:
            result = await self.scan_file(file_bytes)
            results.append(result)
        return results
    
    async def health_check(self) -> bool:
        """Check ClamAV connection health."""
        try:
            client = self._get_client()
            # Ping command
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, client.ping)
            return result == 'PONG'
        except Exception as e:
            logger.error(f"ClamAV health check failed: {e}")
            return False


def get_clamav_client() -> ClamAVClient:
    """Get the global ClamAV client instance."""
    return ClamAVClient()
