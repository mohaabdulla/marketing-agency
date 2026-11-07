import urllib.request
import urllib.parse
import json

def test_endpoints():
    base = "http://127.0.0.1:8000"
    
    # 1. Health
    with urllib.request.urlopen(f"{base}/api/health") as r:
        print("Health:", r.read().decode())

    # 2. Sample visuals
    with urllib.request.urlopen(f"{base}/api/sample-visuals") as r:
        data = json.loads(r.read().decode())
        print("Sample visuals status:", data.get("status"), "samples count:", len(data.get("samples", [])))
        for s in data.get("samples", []):
            print(" - Sample:", s["id"], "|", s["title"])

    # 3. Test static template_reference and raw_subject
    with urllib.request.urlopen(f"{base}/test_assets/template_reference.jpg") as r:
        b1 = r.read()
        print("Static template_reference:", len(b1), "bytes")
    with urllib.request.urlopen(f"{base}/test_assets/raw_subject.jpg") as r:
        b2 = r.read()
        print("Static raw_subject:", len(b2), "bytes")

    # 4. Test Template Swap with Form Data
    swap_data = urllib.parse.urlencode({
        "template_url": "/test_assets/template_reference.jpg",
        "subject_url": "/test_assets/raw_subject.jpg"
    }).encode("utf-8")
    req = urllib.request.Request(f"{base}/api/template-swap", data=swap_data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req) as r:
        res = json.loads(r.read().decode())
        print("Template swap response status:", res.get("status"), "image_url:", res.get("image_url"))

    # 5. Test Visual Upload (Slot = subject)
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="slot"\r\n\r\n'
        f"subject\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="test_subject.jpg"\r\n'
        f"Content-Type: image/jpeg\r\n\r\n"
    ).encode("utf-8") + b2 + f"\r\n--{boundary}--\r\n".encode("utf-8")
    
    upload_req = urllib.request.Request(f"{base}/api/upload-visual", data=body, method="POST")
    upload_req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    with urllib.request.urlopen(upload_req) as r:
        up_res = json.loads(r.read().decode())
        print("Upload visual status:", up_res.get("status"), "file_url:", up_res.get("file_url"))

    # 6. Test Layout Blueprint Analysis
    analyze_data = urllib.parse.urlencode({
        "image_url": "/test_assets/template_reference.jpg"
    }).encode("utf-8")
    an_req = urllib.request.Request(f"{base}/api/analyze-layout", data=analyze_data, method="POST")
    an_req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(an_req) as r:
        an_res = json.loads(r.read().decode())
        print("Analyze layout status:", an_res.get("status"), "elements count:", an_res.get("elements_count"))
        print("Diagnostic overlay URL:", an_res.get("diagnostic_overlay_url"))

if __name__ == "__main__":
    test_endpoints()
