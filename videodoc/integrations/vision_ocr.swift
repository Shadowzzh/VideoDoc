#!/usr/bin/env swift
// ocr.swift - Local OCR for images using the macOS Vision framework.
// No third-party dependencies; requires macOS 10.13+ and the built-in swift toolchain.
//
// Usage:
//   swift ocr.swift <image_path> [options]
//
// Options:
//   --lang <list>       Comma-separated languages, default: "zh-Hans,en-US"
//   --level <level>     "accurate" (default) or "fast"
//   --zoom <factor>     Upscale the image before OCR (e.g. 2 for small text)
//   --positions         Print each line as "text\tx_pct\ty_pct" (y sorted, top-first)
//   --help              Show this help

import Vision
import AppKit

// ---------- argument parsing ----------

var imagePath: String?
var languages = ["zh-Hans", "en-US"]
var recognitionLevel: VNRequestTextRecognitionLevel = .accurate
var zoomFactor: CGFloat = 1.0
var withPositions = false

let args = CommandLine.arguments
var i = 1
while i < args.count {
    let arg = args[i]
    switch arg {
    case "--help", "-h":
        print("""
        ocr.swift - extract text from a local image using macOS Vision (offline).

        Usage:
          swift ocr.swift <image_path> [options]

        Options:
          --lang <list>       Comma-separated languages, default: "zh-Hans,en-US"
          --level <level>     "accurate" (default) or "fast"
          --zoom <factor>     Upscale the image before OCR (e.g. 2 for small text)
          --positions         Print each line as "text\\tx_pct\\ty_pct" (y sorted, top-first)
          --help              Show this help

        Output: one recognized line per stdout line, ordered top to bottom.
        Exit code 0 on success, 1 on load/OCR failure (error on stderr).
        """)
        exit(0)
    case "--lang":
        i += 1
        if i < args.count { languages = args[i].split(separator: ",").map(String.init) }
    case "--level":
        i += 1
        if i < args.count { recognitionLevel = args[i] == "fast" ? .fast : .accurate }
    case "--zoom":
        i += 1
        if i < args.count, let z = Double(args[i]), z > 0 { zoomFactor = CGFloat(z) }
    case "--positions":
        withPositions = true
    default:
        if imagePath == nil { imagePath = arg }
    }
    i += 1
}

guard let path = imagePath, FileManager.default.fileExists(atPath: path) else {
    fputs("error: image path is required and must exist\n", stderr)
    exit(1)
}

// ---------- image loading ----------

func loadCGImage(from path: String) -> CGImage? {
    guard let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil),
          let original = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
        return nil
    }
    guard zoomFactor > 1.0 else { return original }

    // Upscale by redrawing into a larger bitmap; helps Vision on small text.
    let w = Int(CGFloat(original.width) * zoomFactor)
    let h = Int(CGFloat(original.height) * zoomFactor)
    guard let ctx = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8,
                              bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(),
                              bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else {
        return original
    }
    ctx.interpolationQuality = .high
    ctx.draw(original, in: CGRect(x: 0, y: 0, width: w, height: h))
    return ctx.makeImage() ?? original
}

guard let cgImage = loadCGImage(from: path) else {
    fputs("error: cannot load image '\(path)'\n", stderr)
    exit(1)
}

// ---------- OCR ----------

let request = VNRecognizeTextRequest()
request.recognitionLevel = recognitionLevel
request.recognitionLanguages = languages
request.usesLanguageCorrection = false

let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
do {
    try handler.perform([request])
} catch {
    fputs("error: OCR failed: \(error)\n", stderr)
    exit(1)
}

// Sort top-to-bottom by vertical position; stable tie-break by x.
// request.results 已经是 [VNRecognizedTextObservation]?，无需再做条件转换。
guard let observations = request.results else {
    exit(1)
}
let sorted = observations.sorted {
    let dy = $0.boundingBox.midY - $1.boundingBox.midY
    return dy > 0.02 ? true : (dy < -0.02 ? false : $0.boundingBox.midX < $1.boundingBox.midX)
}

for obs in sorted {
    guard let candidate = obs.topCandidates(1).first else { continue }
    if withPositions {
        print("\(candidate.string)\t\(String(format: "%.2f", obs.boundingBox.midX))\t\(String(format: "%.2f", obs.boundingBox.midY))")
    } else {
        print(candidate.string)
    }
}
