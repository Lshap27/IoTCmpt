# Vision models

`pose_landmarker_full.task` is the official MediaPipe Pose Landmarker Full
float16 bundle used by the gateway. It is committed so deployments never
download or replace a model at runtime.

- Source: `https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task`
- SHA-256: `4EAA5EB7A98365221087693FCC286334CF0858E2EB6E15B506AA4A7ECDCEC4AD`
- Runtime path: `AIOT_POSE_MODEL_PATH`
- The server never downloads or replaces this model at runtime.

`efficientdet_lite0_int8.tflite` is the official MediaPipe-compatible
EfficientDet-Lite0 int8 object detector. The gateway restricts it to the COCO
`person` category and uses the result independently from posture landmarks.

- Source: `https://storage.googleapis.com/mediapipe-models/object_detector/efficientdet_lite0/int8/latest/efficientdet_lite0.tflite`
- SHA-256: `0720BF247BD76E6594EA28FA9C6F7C5242BE774818997DBBEFFC4DA460C723BB`
- Runtime path: `AIOT_PERSON_DETECTION_MODEL_PATH`
- The server never downloads or replaces this model at runtime.
