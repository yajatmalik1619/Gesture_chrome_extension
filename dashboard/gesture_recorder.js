import {
    HandLandmarker,
    FilesetResolver,
    DrawingUtils
} from "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.0";

export class GestureRecorder {
    constructor() {
        this.handLandmarker = undefined;
        this.webcamRunning = false;
        this.video = document.getElementById("webcam");
        this.canvasElement = document.getElementById("output_canvas");
        this.canvasCtx = this.canvasElement.getContext("2d");
        this.drawingUtils = undefined;
        this.results = undefined;
        this.lastVideoTime = -1;
        this.isRecording = false;
        this.recordedFrames = [];
    }

    async initialize() {
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

        this.drawingUtils = new DrawingUtils(this.canvasCtx);
        this.startWebcam();
    }

    async startWebcam() {
        if (!this.handLandmarker) {
            console.log("Wait! objectDetector not loaded yet.");
            return;
        }

        const constraints = {
            video: true
        };

        try {
            const stream = await navigator.mediaDevices.getUserMedia(constraints);
            this.video.srcObject = stream;
            this.video.addEventListener("loadeddata", () => this.predictWebcam());
            this.webcamRunning = true;
        } catch (err) {
            console.error("Error accessing webcam: ", err);
        }
    }

    async predictWebcam() {
        // Resize canvas to match video
        this.canvasElement.width = this.video.videoWidth;
        this.canvasElement.height = this.video.videoHeight;

        let startTimeMs = performance.now();
        if (this.lastVideoTime !== this.video.currentTime) {
            this.lastVideoTime = this.video.currentTime;
            this.results = this.handLandmarker.detectForVideo(this.video, startTimeMs);
        }

        this.canvasCtx.save();
        this.canvasCtx.clearRect(0, 0, this.canvasElement.width, this.canvasElement.height);

        if (this.results.landmarks) {
            if (this.isRecording) {
                // Collect landmarks for the first hand detected
                this.recordedFrames.push(this.results.landmarks[0]);
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

        if (this.webcamRunning) {
            window.requestAnimationFrame(() => this.predictWebcam());
        }
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
