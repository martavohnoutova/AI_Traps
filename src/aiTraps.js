/**
 * AI Traps Manager - Frontend Module
 * Manages video trap playback based on room asset state.
 */

export class AiTraps {
    constructor(videoElement, imageElement) {
        this.videoElement = videoElement;
        this.imageElement = imageElement;
    }

    play(videoUrl) {
        if (!videoUrl) return;
        // Skryjeme image a zobrazíme video
        this.imageElement.style.display = 'none';
        this.videoElement.style.display = 'block';
        this.videoElement.src = videoUrl;
        this.videoElement.loop = false;
        this.videoElement.currentTime = 0;
        this.videoElement.play().catch(() => {});
        this.videoElement.onended = () => {
            this.videoElement.style.display = 'none';
            const staticImage = videoUrl.replace('.mp4', '.png');
            this.imageElement.src = staticImage;
            this.imageElement.style.display = 'block';
        };
        this.videoElement.onerror = () => {
            this.videoElement.style.display = 'none';
            const staticImage = videoUrl.replace('.mp4', '.png');
            this.imageElement.src = staticImage;
            this.imageElement.style.display = 'block';
        };
    }
}
