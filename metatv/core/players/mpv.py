"""MPV player plugin implementation"""

import subprocess
import json
import socket
import os
import shutil
from typing import Optional
from loguru import logger

from metatv.core.players.base import PlayerPlugin, QueueMode
from metatv.core.config import Config


class MPVPlayer(PlayerPlugin):
    """MPV media player implementation with single-instance IPC support"""
    
    def __init__(self, config: Config):
        """Initialize MPV player
        
        Args:
            config: Application configuration
        """
        self.config = config
        self.process: Optional[subprocess.Popen] = None
        self.socket_path = config.mpv_socket_path
        self.single_instance = (config.player_mode == "single-instance")
    
    @property
    def name(self) -> str:
        """Player name"""
        return "mpv"
    
    def is_available(self) -> bool:
        """Check if mpv is available on system"""
        return shutil.which("mpv") is not None
    
    def is_running(self) -> bool:
        """Check if mpv process is currently running"""
        if self.process is None:
            return False
        return self.process.poll() is None
    
    def _ensure_single_instance_running(self) -> bool:
        """Ensure single mpv instance is running with IPC socket
        
        Returns:
            True if instance is ready, False otherwise
        """
        if not self.single_instance:
            return False
        
        # Check if already running
        if self.is_running():
            return True
        
        # Remove stale socket
        if os.path.exists(self.socket_path):
            try:
                os.remove(self.socket_path)
                logger.info(f"Removed stale socket: {self.socket_path}")
            except Exception as e:
                logger.warning(f"Could not remove stale socket: {e}")
        
        # Start mpv with IPC socket
        try:
            cmd = [
                "mpv",
                f"--input-ipc-server={self.socket_path}",
                "--force-window=yes",  # Show window immediately
                "--keep-open=no"  # Don't pause at end of video
            ]
            
            # Configure idle behavior (whether to quit when playlist is empty)
            if self.config.close_player_when_finished:
                # Quit after video finishes (will restart quickly on next play)
                cmd.append("--idle=once")
            else:
                # Keep window open for next video (instant channel switching)
                cmd.append("--idle=yes")
            
            cmd += self.config.mpv_extra_args
            
            logger.info(f"Starting single mpv instance: {' '.join(cmd)}")
            
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
            logger.info(f"Started single mpv instance with PID {self.process.pid}")
            
            # Wait briefly for socket to be created
            import time
            for _ in range(10):  # Wait up to 1 second
                if os.path.exists(self.socket_path):
                    logger.info(f"Socket ready: {self.socket_path}")
                    return True
                time.sleep(0.1)
            
            logger.warning("Socket not created within timeout")
            return False
            
        except Exception as e:
            logger.error(f"Failed to start single mpv instance: {e}")
            return False
    
    def _send_ipc_command(self, command: dict) -> bool:
        """Send IPC command to mpv socket
        
        Args:
            command: JSON command dict
            
        Returns:
            True if successful, False otherwise
        """
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(2.0)
            sock.connect(self.socket_path)
            
            command_json = json.dumps(command) + "\n"
            sock.sendall(command_json.encode('utf-8'))
            
            # Read response
            response = sock.recv(4096).decode('utf-8')
            sock.close()
            
            logger.debug(f"IPC command sent: {command}, response: {response}")
            return True
            
        except FileNotFoundError:
            logger.error(f"Socket not found: {self.socket_path}")
            return False
        except socket.timeout:
            logger.warning("IPC command timed out")
            return False
        except Exception as e:
            logger.error(f"IPC command failed: {e}")
            return False
    
    def play(self, url: str, title: str) -> bool:
        """Play a URL
        
        Args:
            url: Stream URL to play
            title: Title to display
            
        Returns:
            True if successful, False otherwise
        """
        logger.info(f"MPVPlayer.play: {title}")
        logger.info(f"  URL: {url}")
        logger.info(f"  Mode: {'single-instance' if self.single_instance else 'new-instance'}")
        
        if self.single_instance:
            # Use single instance with IPC
            if not self._ensure_single_instance_running():
                logger.warning("Could not start single instance, falling back to new instance")
                return self._launch_new_instance(url, title)
            
            # Send loadfile command via IPC
            command = {
                "command": ["loadfile", url, "replace"],
                "request_id": 1
            }
            
            if self._send_ipc_command(command):
                # Set media title
                title_command = {
                    "command": ["set_property", "force-media-title", title],
                    "request_id": 2
                }
                self._send_ipc_command(title_command)
                
                logger.info(f"Sent to single mpv instance: {title}")
                return True
            else:
                logger.warning("IPC command failed, falling back to new instance")
                return self._launch_new_instance(url, title)
        else:
            # Launch new instance
            return self._launch_new_instance(url, title)
    
    def queue(self, url: str, title: str, mode: QueueMode = QueueMode.APPEND_PLAY) -> bool:
        """Add URL to playlist queue
        
        Args:
            url: Stream URL to queue
            title: Title to display
            mode: How to add to queue
            
        Returns:
            True if successful, False otherwise
            
        Note:
            mpv's IPC protocol doesn't support setting titles for queued playlist items.
            All queued items will show the currently playing item's title until they
            start playing. To fix this properly, we need to implement the IPC event
            system (Phase 4) to listen for playlist-pos changes and set titles when
            each file starts playing.
        """
        logger.info(f"MPVPlayer.queue: {title} (mode: {mode.value})")
        
        if not self.single_instance:
            logger.warning("Queue mode requires single-instance mode")
            return self.play(url, title)
        
        if not self._ensure_single_instance_running():
            logger.warning("Could not start single instance")
            return False
        
        # Map QueueMode to mpv loadfile flag
        mode_map = {
            QueueMode.REPLACE: "replace",
            QueueMode.APPEND: "append",
            QueueMode.APPEND_PLAY: "append-play",
            QueueMode.INSERT_NEXT: "insert-next"
        }
        
        mpv_mode = mode_map.get(mode, "append-play")
        
        # Send loadfile command with appropriate flag
        # TODO: Set title when file starts playing (requires IPC event monitoring)
        command = {
            "command": ["loadfile", url, mpv_mode],
            "request_id": 1
        }
        
        if self._send_ipc_command(command):
            logger.info(f"Queued to mpv: {title}")
            return True
        else:
            logger.error(f"Failed to queue: {title}")
            return False
    
    def _launch_new_instance(self, url: str, title: str) -> bool:
        """Launch new mpv instance for URL
        
        Args:
            url: Stream URL
            title: Title to display
            
        Returns:
            True if successful, False otherwise
        """
        try:
            cmd = [
                "mpv",
                f"--force-media-title={title}"
            ] + self.config.mpv_extra_args + [url]
            
            logger.info(f"Launching new mpv instance: {' '.join(cmd[:3])}...")
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
            logger.info(f"mpv process started with PID: {process.pid}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to launch mpv: {e}")
            return False
    
    def stop(self) -> bool:
        """Stop playback
        
        Returns:
            True if successful, False otherwise
        """
        logger.info("Stopping mpv playback")
        
        if self.single_instance and self.is_running():
            # Send quit command via IPC
            command = {"command": ["quit"], "request_id": 1}
            return self._send_ipc_command(command)
        
        return False
    
    def cleanup(self):
        """Cleanup resources (terminate process, remove socket)"""
        logger.info("Cleaning up MPVPlayer resources")
        
        # Terminate process if running
        if self.is_running():
            logger.info("Terminating mpv process")
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                logger.warning("mpv did not terminate, killing")
                self.process.kill()
        
        # Remove socket
        if os.path.exists(self.socket_path):
            try:
                os.remove(self.socket_path)
                logger.info(f"Removed socket: {self.socket_path}")
            except Exception as e:
                logger.warning(f"Could not remove socket: {e}")
