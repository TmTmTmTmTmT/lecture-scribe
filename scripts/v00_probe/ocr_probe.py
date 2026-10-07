"""V-00-3: Vision OCR 품질/시간 측정. usage: ocr_probe.py IMG..."""
import sys, time
import Vision, Quartz
from Foundation import NSURL

def ocr(path):
    url = NSURL.fileURLWithPath_(path)
    src = Quartz.CGImageSourceCreateWithURL(url, None)
    img = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    req.setRecognitionLanguages_(["ko-KR", "en-US"])
    req.setUsesLanguageCorrection_(True)
    h = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(img, None)
    ok, err = h.performRequests_error_([req], None)
    out = []
    for o in req.results() or []:
        c = o.topCandidates_(1)[0]
        bb = o.boundingBox()
        out.append((c.string(), float(c.confidence()), round(bb.origin.x,3), round(bb.origin.y+bb.size.height,3)))
    return out

for p in sys.argv[1:]:
    t = time.time(); r = ocr(p); dt = time.time() - t
    print(f"== {p}  {dt:.2f}s  {len(r)} lines")
    for s, c, x, y in r:
        print(f"  {c:.2f} x={x:.2f} y={y:.2f}  {s}")
