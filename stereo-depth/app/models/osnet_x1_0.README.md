# OSNet x1.0 — Market1501

Source : https://hailo-model-zoo.s3.eu-west-2.amazonaws.com/PersonReID/osnet_x1_0/2022-05-19/osnet_x1_0.zip
Configuration : https://github.com/hailo-ai/hailo_model_zoo/blob/master/hailo_model_zoo/cfg/networks/osnet_x1_0.yaml
Modèle d’origine : https://github.com/KaiyangZhou/deep-person-reid (MIT, selon catalogue Hailo).
SHA256 ONNX : 5af439e3ad6e753d632e51e6f350f198024bcc820629d3e2bb1bf9bc2955e462
Entrée RGB NCHW 256x128, normalisation ImageNet ; sortie 512 valeurs, normalisée L2.
Exécution OpenCV CPU. Ne pas confondre similarité cosinus et probabilité d’identité.
