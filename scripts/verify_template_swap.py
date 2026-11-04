"""
Autonomous Template Subject-Replacement & 2.5D Pop-Out Verification Suite
==========================================================================
Verifies:
1. Full-Image SSIM >= 0.93
2. Background/Typography Region SSIM >= 0.97
3. Subject Silhouette IoU >= 0.92
4. Monochrome Subject HSV Saturation < 0.02
5. Hair Edge Halo Check == 0 bright off-white fringe against background
6. Generates 4-panel diagnostic debug_comparison.jpg
"""

import sys
import argparse
from pathlib import Path
import cv2
import numpy as np
from skimage.metrics import structural_similarity as ssim
from PIL import Image

# Ensure repository root is in sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from visual_engine import composite_template_swap


def verify_template_swap(
    template_path: Path,
    subject_path: Path,
    target_path: Path,
    output_path: Path,
    diagnostic_path: Path,
) -> bool:
    print("\n" + "=" * 70)
    print("  AUTONOMOUS TEMPLATE SUBJECT-REPLACEMENT VERIFICATION")
    print("=" * 70)
    print(f" Template:   {template_path}")
    print(f" Subject:    {subject_path}")
    print(f" Target GT:  {target_path}")

    # Load ground truth
    target_bgr = cv2.imread(str(target_path))
    if target_bgr is None:
        raise FileNotFoundError(f"Could not load target ground truth: {target_path}")
    H, W, _ = target_bgr.shape

    # 1. Run Autonomous Pop-Out Compositor
    print("\n[1/5] Running visual_engine.composite_template_swap()...")
    result_pil = composite_template_swap(template_path, subject_path, target_size=(W, H))
    result_pil.save(output_path, quality=95)
    print(f"      Saved output to {output_path}")

    # Convert generated output to BGR for cv2 analysis
    gen_bgr = cv2.cvtColor(np.array(result_pil), cv2.COLOR_RGB2BGR)

    # Resize template for baseline comparison
    t1_bgr = cv2.imread(str(template_path))
    t1_res = cv2.resize(t1_bgr, (W, H), interpolation=cv2.INTER_LANCZOS4)

    # 2. Compute Full-Image SSIM
    print("\n[2/5] Evaluating Structural Similarity (SSIM)...")
    gen_gray = cv2.cvtColor(gen_bgr, cv2.COLOR_BGR2GRAY)
    target_gray = cv2.cvtColor(target_bgr, cv2.COLOR_BGR2GRAY)

    full_ssim = float(ssim(gen_gray, target_gray))

    # Background / Typography Region SSIM: outside frame and lower caption
    y_grid, x_grid = np.mgrid[0:H, 0:W]
    bg_mask = (y_grid < 180) | (y_grid > 798) | (x_grid < 180) | (x_grid > 627)
    bg_ssim = float(ssim(gen_gray[bg_mask], target_gray[bg_mask]))

    # 3. Compute Subject Silhouette IoU
    print("\n[3/5] Evaluating Subject Silhouette IoU & Monochrome Grading...")
    hsv_gen = cv2.cvtColor(gen_bgr, cv2.COLOR_BGR2HSV)
    hsv_target = cv2.cvtColor(target_bgr, cv2.COLOR_BGR2HSV)

    # Subject search area: frame window + head pop-out above
    subject_area = (y_grid >= 205) & (y_grid < 668) & (x_grid >= 195) & (x_grid <= 612)
    mask_gen = (hsv_gen[:, :, 1] < 35) & (hsv_gen[:, :, 2] < 240) & subject_area
    mask_target = (hsv_target[:, :, 1] < 35) & (hsv_target[:, :, 2] < 240) & subject_area

    intersection = np.sum(mask_gen & mask_target)
    union = np.sum(mask_gen | mask_target)
    iou = float(intersection / union) if union > 0 else 0.0

    # 4. Monochrome Verification
    mean_sat = float(np.mean(hsv_gen[:, :, 1][mask_gen])) / 255.0

    # 5. Hair Edge Halo Check against blue background
    print("\n[4/5] Checking Hair Edge Halos & Studio Fringe...")
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    hair_top = mask_gen.copy()
    hair_top[294:, :] = False # top head pop-out only
    dilated_hair = cv2.dilate(hair_top.astype(np.uint8), kernel)
    outer_contour = (dilated_hair > 0) & (~mask_gen)

    # Exclude text in WELCOME region (light letters) and top frame border
    is_above_frame = (y_grid < 294)
    hsv_t1 = cv2.cvtColor(t1_res, cv2.COLOR_BGR2HSV)
    is_text = (hsv_t1[:, :, 1] < 60) & (hsv_t1[:, :, 2] > 180)
    outer_blue = outer_contour & is_above_frame & (~is_text)

    hsv_outer = hsv_gen[outer_blue]
    halos = int(np.sum((hsv_outer[:, 1] < 30) & (hsv_outer[:, 2] > 200)))

    # 6. Generate 4-Panel Diagnostic
    print("\n[5/5] Generating 4-Panel Visual Diagnostic...")
    diff = cv2.absdiff(gen_bgr, target_bgr)
    diff_gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
    heatmap = cv2.applyColorMap(diff_gray * 3, cv2.COLORMAP_JET)

    panel_w, panel_h = W // 2, H // 2
    p1 = cv2.resize(t1_res, (panel_w, panel_h))
    p2 = cv2.resize(gen_bgr, (panel_w, panel_h))
    p3 = cv2.resize(target_bgr, (panel_w, panel_h))
    p4 = cv2.resize(heatmap, (panel_w, panel_h))

    def add_label(img, text):
        canvas = img.copy()
        cv2.rectangle(canvas, (0, 0), (panel_w, 36), (0, 0, 0), -1)
        cv2.putText(canvas, text, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2, cv2.LINE_AA)
        return canvas

    p1 = add_label(p1, "1: Template Reference")
    p2 = add_label(p2, "2: Generated Output")
    p3 = add_label(p3, "3: Target Ground Truth")
    p4 = add_label(p4, "4: Pixel Diff Heatmap (x3)")

    comparison = np.hstack([p1, p2, p3, p4])
    cv2.imwrite(str(diagnostic_path), comparison)
    print(f"      Saved diagnostic to {diagnostic_path}")

    # Results Table
    checks = [
        ("Full-Image SSIM", full_ssim, ">= 0.93", full_ssim >= 0.93),
        ("Background Region SSIM", bg_ssim, ">= 0.97", bg_ssim >= 0.97),
        ("Subject Silhouette IoU", iou, ">= 0.92", iou >= 0.92),
        ("Subject Mean Saturation", mean_sat, "< 0.02", mean_sat < 0.02),
        ("Hair Fringe Halo Count", halos, "== 0", halos == 0),
    ]

    print("\n" + "-" * 70)
    print(f"{'METRIC':<28} {'VALUE':<12} {'THRESHOLD':<12} {'STATUS':<8}")
    print("-" * 70)
    all_passed = True
    for name, val, thresh, passed in checks:
        if isinstance(val, float):
            val_str = f"{val:.4f}"
        else:
            val_str = str(val)
        status_str = "PASS" if passed else "FAIL"
        print(f"{name:<28} {val_str:<12} {thresh:<12} {status_str:<8}")
        if not passed:
            all_passed = False
    print("-" * 70)

    if all_passed:
        print("\n>>> ALL CRITERIA PASSED: Output matches Image 3 geometry and quality. <<<\n")
    else:
        print("\n>>> ONE OR MORE CRITERIA FAILED. Review parameters and retry. <<<\n")

    return all_passed


def main():
    parser = argparse.ArgumentParser(description="Verify template subject-replacement and pop-out compositing.")
    parser.add_argument("--template", default=str(ROOT / "test_assets" / "template_reference.jpg"))
    parser.add_argument("--subject", default=str(ROOT / "test_assets" / "raw_subject.jpg"))
    parser.add_argument("--target", default=str(ROOT / "test_assets" / "target_ground_truth.jpg"))
    parser.add_argument("--output", default=str(ROOT / "test_assets" / "generated_output.jpg"))
    parser.add_argument("--diagnostic", default=str(ROOT / "test_assets" / "debug_comparison.jpg"))

    args = parser.parse_args()

    success = verify_template_swap(
        Path(args.template),
        Path(args.subject),
        Path(args.target),
        Path(args.output),
        Path(args.diagnostic),
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

