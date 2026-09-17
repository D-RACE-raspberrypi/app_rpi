"""Metric stereo geometry. All internal distances are metres."""
from dataclasses import dataclass, asdict
import cv2
import numpy as np

SIZE = (640, 480)
BOARD = (9, 6)  # inner corners; 10 x 7 printed squares


def ideal_geometry():
    """Trial assumptions only, not measured Module 3 intrinsics."""
    k = np.array([[500., 0., SIZE[0]/2], [0., 500., SIZE[1]/2], [0., 0., 1.]])
    return dict(K1=k, K2=k.copy(), D1=np.zeros(5), D2=np.zeros(5),
                R=np.eye(3), T=np.array([[-.065], [0.], [0.]]))


@dataclass
class DepthSettings:
    preset: str = "balanced"
    near: float = 0.25
    far: float = 4.0
    uniqueness: int = 10
    block_size: int = 5
    tx: float = 0.0  # manual corrections, mm
    ty: float = 0.0
    tz: float = 0.0
    rx: float = 0.0  # manual corrections, degrees
    ry: float = 0.0
    rz: float = 0.0
    trial_y: float = 0.0  # right-image translation, pixels at SIZE; trial only
    trial_roll: float = 0.0  # right-image rotation about its centre, degrees; trial only
    trial_x: float = 0.0
    trial_zoom: float = 0.0  # percent scale change; not a measured Z translation
    trial_pitch: float = 0.0
    trial_yaw: float = 0.0
    texture_sensitivity: float = 50.0  # 0: strict texture rejection; 100: no texture gate

    @classmethod
    def validated(cls, values):
        allowed = asdict(cls())
        if set(values) - set(allowed):
            raise ValueError("Paramètre inconnu.")
        obj = cls(**values)
        if obj.preset not in ("fast", "balanced", "quality"):
            raise ValueError("Profil inconnu.")
        for key in allowed:
            if key != "preset":
                value = getattr(obj, key)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value):
                    raise ValueError("Les réglages doivent être des nombres finis.")
        if not 0.1 <= obj.near < obj.far <= 20:
            raise ValueError("Choisir 0,10 m ≤ minimum < maximum ≤ 20 m.")
        if obj.block_size not in (3, 5, 7, 9) or not 0 <= obj.uniqueness <= 30 or int(obj.uniqueness) != obj.uniqueness:
            raise ValueError("Réglages de correspondance invalides.")
        if any(abs(getattr(obj, k)) > 10 for k in ("tx", "ty", "tz")):
            raise ValueError("Correction de translation limitée à ±10 mm.")
        if any(abs(getattr(obj, k)) > 5 for k in ("rx", "ry", "rz")):
            raise ValueError("Correction de rotation limitée à ±5°.")
        if abs(obj.trial_y) > 120 or abs(obj.trial_roll) > 10:
            raise ValueError("Alignement d'essai limité à ±120 pixels et ±10°.")
        if abs(obj.trial_x) > 160 or abs(obj.trial_zoom) > 60 or abs(obj.trial_pitch) > 10 or abs(obj.trial_yaw) > 10:
            raise ValueError("Correction droite limitée à ±160 px, ±60 % de zoom et ±10° d'inclinaison.")
        if not 0 <= obj.texture_sensitivity <= 100:
            raise ValueError("La sensibilité doit être comprise entre 0 et 100.")
        obj.block_size, obj.uniqueness = int(obj.block_size), int(obj.uniqueness)
        return obj


def object_points(square_mm):
    points = np.zeros((BOARD[0] * BOARD[1], 3), np.float32)
    points[:, :2] = np.mgrid[0:BOARD[0], 0:BOARD[1]].T.reshape(-1, 2)
    points *= square_mm / 1000.0
    return points


def detect_board(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    found, corners = cv2.findChessboardCornersSB(gray, BOARD, flags=cv2.CALIB_CB_NORMALIZE_IMAGE)
    return corners.astype(np.float32) if found else None


def align_corners(left, right):
    # A detector may enumerate the same board in reverse in the other camera.
    if np.dot((left[-1] - left[0]).ravel(), (right[-1] - right[0]).ravel()) < 0:
        right = right[::-1].copy()
    return left, right


def rectification(cal, settings=None, size=SIZE):
    settings = settings or DepthSettings()
    angles = np.deg2rad([settings.rx, settings.ry, settings.rz])
    x, y, z = angles
    rx = np.array([[1, 0, 0], [0, np.cos(x), -np.sin(x)], [0, np.sin(x), np.cos(x)]])
    ry = np.array([[np.cos(y), 0, np.sin(y)], [0, 1, 0], [-np.sin(y), 0, np.cos(y)]])
    rz = np.array([[np.cos(z), -np.sin(z), 0], [np.sin(z), np.cos(z), 0], [0, 0, 1]])
    rotation = rz @ ry @ rx @ cal["R"]
    translation = cal["T"].reshape(3, 1) + np.array([[settings.tx], [settings.ty], [settings.tz]]) / 1000
    if translation[0, 0] >= -0.005 or abs(translation[1, 0]) >= abs(translation[0, 0]):
        raise ValueError("Ordre des caméras ou géométrie incompatible avec une stéréo horizontale. Inverser G/D puis recalibrer.")
    k1, k2 = cal["K1"].copy(), cal["K2"].copy()
    sx, sy = size[0] / SIZE[0], size[1] / SIZE[1]
    k1[0] *= sx; k1[1] *= sy
    k2[0] *= sx; k2[1] *= sy
    r1, r2, p1, p2, q, roi1, roi2 = cv2.stereoRectify(
        k1, cal["D1"], k2, cal["D2"], size, rotation, translation,
        flags=cv2.CALIB_ZERO_DISPARITY, alpha=0)
    maps = [cv2.initUndistortRectifyMap(k, d, r, p, size, cv2.CV_16SC2)
            for k, d, r, p in ((k1, cal["D1"], r1, p1), (k2, cal["D2"], r2, p2))]
    return maps, q, (r1, r2, p1, p2), (roi1, roi2)


def calibrate(samples, square_mm):
    if len(samples) < 12:
        raise ValueError("Au moins 12 paires différentes sont nécessaires ; 20 à 30 sont recommandées.")
    objects = [object_points(square_mm) for _ in samples]
    left = [s[0] for s in samples]
    right = [s[1] for s in samples]
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 1e-7)
    rms1, k1, d1, _, _ = cv2.calibrateCamera(objects, left, SIZE, None, None, flags=cv2.CALIB_FIX_K3)
    rms2, k2, d2, _, _ = cv2.calibrateCamera(objects, right, SIZE, None, None, flags=cv2.CALIB_FIX_K3)
    rms, k1, d1, k2, d2, r, t, _, _ = cv2.stereoCalibrate(
        objects, left, right, k1, d1, k2, d2, SIZE,
        criteria=criteria, flags=cv2.CALIB_FIX_INTRINSIC)
    cal = dict(K1=k1, D1=d1, K2=k2, D2=d2, R=r, T=t)
    if not all(np.isfinite(v).all() for v in cal.values()):
        raise ValueError("Calibration non convergente : varier les angles et la position de la mire.")
    _, _, (r1, r2, p1, p2), _ = rectification(cal)
    errors = []
    for l, rr in samples:
        a = cv2.undistortPoints(l, k1, d1, R=r1, P=p1)
        b = cv2.undistortPoints(rr, k2, d2, R=r2, P=p2)
        errors.append(float(np.mean(np.abs(a[:, 0, 1] - b[:, 0, 1]))))
    baseline = float(np.linalg.norm(t) * 1000)
    if rms > 3 or np.mean(errors) > 2 or not 20 <= baseline <= 120:
        raise ValueError(f"Calibration insuffisante : RMS {rms:.2f} px, écart vertical {np.mean(errors):.2f} px, base {baseline:.1f} mm. Vérifier la taille des cases et refaire des prises variées.")
    warnings = []
    if rms > 1 or np.mean(errors) > 0.6:
        warnings.append("Précision perfectible : ajouter des vues inclinées et dans les coins.")
    if abs(baseline - 65) > 9:
        warnings.append("La base mesurée s'écarte de 65 mm : vérifier la dimension imprimée des cases.")
    report = dict(rms=float(rms), rms_left=float(rms1), rms_right=float(rms2),
                  epipolar_px=float(np.mean(errors)), per_view_px=errors, baseline_mm=baseline,
                  translation_mm=(t.ravel() * 1000).tolist(),
                  rotation_deg=list(cv2.RQDecomp3x3(r)[0]),
                  samples=len(samples), square_mm=square_mm, warnings=warnings)
    return cal, report


class DepthProcessor:
    def __init__(self, cal, settings, trial=False):
        self.settings = settings
        self.trial = trial
        self.size = (384, 288) if settings.preset == "fast" else SIZE
        # Manual image alignment has a fixed left reference. Legacy stereo-pose
        # offsets must never feed stereoRectify here (it would move BOTH views).
        self.maps, self.q, geometry, rois = rectification(ideal_geometry() if trial else cal,
                                                  DepthSettings() if trial else settings, self.size)
        self.left_rotation, _, self.left_projection, _ = geometry
        self.trial_transform = None
        self.right_support = np.full(self.size[::-1], 255, np.uint8)
        if trial:
            cx, cy = self.size[0]/2, self.size[1]/2
            sx, sy = self.size[0]/SIZE[0], self.size[1]/SIZE[1]
            k = np.array([[500*sx, 0., cx], [0., 500*sy, cy], [0., 0., 1.]])
            pitch, yaw = np.deg2rad([settings.trial_pitch, settings.trial_yaw])
            rx = np.array([[1,0,0], [0,np.cos(pitch),-np.sin(pitch)], [0,np.sin(pitch),np.cos(pitch)]])
            ry = np.array([[np.cos(yaw),0,np.sin(yaw)], [0,1,0], [-np.sin(yaw),0,np.cos(yaw)]])
            affine = np.eye(3)
            affine[:2] = cv2.getRotationMatrix2D((cx,cy), settings.trial_roll, 1+settings.trial_zoom/100)
            affine[0,2] += settings.trial_x*sx
            affine[1,2] += settings.trial_y*sy
            self.trial_transform = affine @ k @ ry @ rx @ np.linalg.inv(k)
            self.right_support = cv2.warpPerspective(self.right_support, self.trial_transform, self.size)
        self.right_support = cv2.erode(self.right_support, np.ones((9, 9), np.uint8)) > 254
        disparities = 64 if settings.preset == "fast" else 96
        b = settings.block_size
        self.matcher = cv2.StereoSGBM_create(
            minDisparity=0, numDisparities=disparities, blockSize=b,
            P1=8*b*b, P2=32*b*b, disp12MaxDiff=1,
            uniquenessRatio=settings.uniqueness, speckleWindowSize=80,
            speckleRange=2, preFilterCap=31, mode=cv2.STEREO_SGBM_MODE_SGBM_3WAY)
        self.wls = None
        if hasattr(cv2, "ximgproc"):
            self.right_matcher = cv2.ximgproc.createRightMatcher(self.matcher)
        else:
            self.right_matcher = cv2.StereoSGBM_create(
                minDisparity=1-disparities, numDisparities=disparities, blockSize=b,
                P1=8*b*b, P2=32*b*b, disp12MaxDiff=1, uniquenessRatio=settings.uniqueness,
                speckleWindowSize=80, speckleRange=2, preFilterCap=31,
                mode=cv2.STEREO_SGBM_MODE_SGBM_3WAY)
        self.right_min = 1-disparities
        if settings.preset == "quality" and hasattr(cv2, "ximgproc"):
            self.right_matcher = cv2.ximgproc.createRightMatcher(self.matcher)
            self.wls = cv2.ximgproc.createDisparityWLSFilter(self.matcher)
            self.wls.setLambda(8000); self.wls.setSigmaColor(1.5)
        self.roi = cv2.getValidDisparityROI(rois[0], rois[1], 0, disparities, b)
        self.grid_x, self.grid_y = np.meshgrid(np.arange(self.size[0]), np.arange(self.size[1]))

    @staticmethod
    def textured(gray, sensitivity=50):
        if sensitivity >= 100:
            return np.ones(gray.shape, dtype=bool)
        values = gray.astype(np.float32)
        mean = cv2.boxFilter(values, -1, (9, 9))
        variance = cv2.boxFilter(values*values, -1, (9, 9)) - mean*mean
        minimum_contrast = 6 * (1 - sensitivity/100)
        return variance > minimum_contrast**2

    def process(self, left, right):
        if left.shape[1::-1] != self.size:
            left, right = [cv2.resize(v, self.size, interpolation=cv2.INTER_AREA) for v in (left, right)]
        if not self.trial:
            left, right = [cv2.remap(v, *m, cv2.INTER_LINEAR) for v, m in zip((left, right), self.maps)]
        if self.trial_transform is not None:
            right = cv2.warpPerspective(right, self.trial_transform, self.size)
        l, r = [cv2.cvtColor(v, cv2.COLOR_BGR2GRAY) for v in (left, right)]
        raw = self.matcher.compute(l, r)
        reverse = self.right_matcher.compute(r, l)
        confidence = raw > 0
        if self.wls:
            raw = self.wls.filter(raw, l, None, reverse)
            confidence &= self.wls.getConfidenceMap() > 128
        disparity = raw.astype(np.float32) / 16
        xr = np.rint(self.grid_x - disparity).astype(np.int32)
        inside = (xr >= 0) & (xr < self.size[0])
        xr = np.clip(xr, 0, self.size[0]-1)
        reverse_at_match = reverse[self.grid_y, xr].astype(np.float32)/16
        confidence &= inside & (reverse_at_match >= self.right_min) & (reverse_at_match < 0)
        confidence &= np.abs(disparity + reverse_at_match) <= 1.0
        confidence &= self.textured(l, self.settings.texture_sensitivity)
        confidence &= self.textured(r, self.settings.texture_sensitivity)[self.grid_y, xr]
        confidence &= self.right_support[self.grid_y, xr]
        xyz = cv2.reprojectImageTo3D(disparity, self.q)
        depth = xyz[:, :, 2]
        roi_mask = np.zeros(l.shape, bool)
        x, y, w, h = self.roi
        roi_mask[y:y+h, x:x+w] = True
        self.range_depth = np.where(confidence & roi_mask & (disparity > 0) & np.isfinite(depth) & (depth >= self.settings.near), depth, np.nan).astype(np.float32)
        valid = confidence & roi_mask & (disparity > 0) & np.isfinite(depth) & (depth >= self.settings.near) & (depth <= self.settings.far)
        depth = np.where(valid, depth, np.nan).astype(np.float32)
        normalized = np.clip((self.settings.far - np.nan_to_num(depth, nan=self.settings.far)) / (self.settings.far - self.settings.near), 0, 1)
        color = cv2.applyColorMap((normalized * 255).astype(np.uint8), cv2.COLORMAP_TURBO)
        color[~valid] = (25, 21, 18)
        return left, right, color, depth, disparity, float(valid.mean()*100)
