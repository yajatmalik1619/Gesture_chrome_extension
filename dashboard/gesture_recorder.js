import {
    HandLandmarker,
    FilesetResolver,
    DrawingUtils
} from "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.0";

export class GestureRecorder {
    constructor() {
        this.handLandmarker = undefined;
        this.webcamRunning = false;
        this.video = null;
        this.canvasElement = null;
        this.canvasCtx = null;
        this.drawingUtils = undefined;
        this.results = undefined;
        this.lastVideoTime = -1;
        this.isRecording = false;
        this.recordedFrames = [];
        this.stream = null;
    }

    async initialize(videoId, canvasId) {
        this.setTargetElements(videoId, canvasId);

        const vision = await FilesetResolver.forVisionTasks(
            "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.0/wasm"
        );
        this.handLandmarker = await HandLandmarker.createFromOptions(vision, {
            baseOptions: {
                modelAssetPath: `https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task`,
                delegate: "GPU"
            },
            runningMode: "VIDEO",
            numHands: 2
        });

        await this.startWebcam();
    }

    setTargetElements(videoId, canvasId) {
        this.video = document.getElementById(videoId);
        this.canvasElement = document.getElementById(canvasId);
        if (this.canvasElement) {
            this.canvasCtx = this.canvasElement.getContext("2d");
            this.drawingUtils = new DrawingUtils(this.canvasCtx);
        }

        // If we already have a stream, attach it to the new video element
        if (this.stream && this.video) {
            this.video.srcObject = this.stream;
        }
    }

    async startWebcam() {
        if (!this.handLandmarker) return;

        const constraints = { video: true };
        try {
            this.stream = await navigator.mediaDevices.getUserMedia(constraints);
            if (this.video) {
                this.video.srcObject = this.stream;
                this.video.addEventListener("loadeddata", () => this.predictWebcam());
            }
            this.webcamRunning = true;
        } catch (err) {
            console.error("Error accessing webcam: ", err);
        }
    }

    async predictWebcam() {
        if (!this.webcamRunning || !this.video || !this.canvasElement) {
            window.requestAnimationFrame(() => this.predictWebcam());
            return;
        }

        // Resize canvas to match video
        if (this.video.videoWidth > 0 && this.canvasElement.width !== this.video.videoWidth) {
            this.canvasElement.width = this.video.videoWidth;
            this.canvasElement.height = this.video.videoHeight;
        }

        let startTimeMs = performance.now();
        if (this.lastVideoTime !== this.video.currentTime) {
            this.lastVideoTime = this.video.currentTime;
            this.results = this.handLandmarker.detectForVideo(this.video, startTimeMs);
        }

        this.canvasCtx.save();
        this.canvasCtx.clearRect(0, 0, this.canvasElement.width, this.canvasElement.height);

        const handDetected = this.results && this.results.landmarks && this.results.landmarks.length > 0;

        // Notify callback if exists
        if (this.onResults) {
            this.onResults(this.results);
        }

        if (handDetected) {
            if (this.isRecording && this.results.landmarks[0]) {
                const landmarks = this.results.landmarks[0];
                this.recordedFrames.push(landmarks);
            }

            for (const landmarks of this.results.landmarks) {
                this.drawingUtils.drawConnectors(landmarks, HandLandmarker.HAND_CONNECTIONS, {
                    color: "#6366f1",
                    lineWidth: 5
                });
                this.drawingUtils.drawLandmarks(landmarks, {
                    color: "#ffffff",
                    lineWidth: 2,
                    radius: 3
                });
            }
        }
        this.canvasCtx.restore();

        window.requestAnimationFrame(() => this.predictWebcam());
    }

    startRecording() {
        this.isRecording = true;
        this.recordedFrames = [];
    }

    stopRecording() {
        this.isRecording = false;
        return this.recordedFrames;
    }
}
