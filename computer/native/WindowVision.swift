// Local, read-only analysis of host-captured images. No app control or network.
import Foundation
import Vision
import CoreGraphics
import ImageIO
import CryptoKit

func visionJSON(_ value:Any) -> Data { (try? JSONSerialization.data(withJSONObject:value,options:[.sortedKeys])) ?? Data() }
func visionError(_ code:String) -> [String:Any] { ["status":"error","error":code,"action_sent":false,"cloud_sent":false] }
func visionSHA(_ data:Data) -> String { SHA256.hash(data:data).map{String(format:"%02x",$0)}.joined() }

final class VisionReply: @unchecked Sendable {
    let lock=NSLock();var value:[String:Any]?
    func publish(_ result:[String:Any]) { lock.lock();value=result;lock.unlock() }
    func read() -> [String:Any]? { lock.lock();defer{lock.unlock()};return value }
}

final class WindowVision {
    let root:URL
    var terminateAfterResponse=false
    init(_ path:String) { root=URL(fileURLWithPath:path).standardizedFileURL.resolvingSymlinksInPath() }
    func load(_ value:Any?, _ sha:Any?) -> (CGImage,String)? {
        guard let path=value as? String, path.hasPrefix("/"), let expected=sha as? String, expected.count==64 else { return nil }
        let url=URL(fileURLWithPath:path).standardizedFileURL
        guard url.path.hasPrefix(root.path+"/"), url.resolvingSymlinksInPath()==url,
              let metadata=try? url.resourceValues(forKeys:[.isRegularFileKey,.isSymbolicLinkKey,.fileSizeKey]),
              metadata.isRegularFile==true, metadata.isSymbolicLink != true,
              let size=metadata.fileSize, size>0, size<=8_388_608,
              let data=try? Data(contentsOf:url), visionSHA(data)==expected,
              let source=CGImageSourceCreateWithData(data as CFData,nil),let image=CGImageSourceCreateImageAtIndex(source,0,nil),
              image.width>0,image.height>0,image.width*image.height<=16_777_216 else { return nil }
        return (image,expected)
    }
    func execute(_ r:[String:Any]) -> [String:Any] {
        let op=r["op"] as? String ?? ""
        if op=="status" { return ["status":"ok","vision_protocol":1,"implementation":"Apple_Vision_local_OCR_and_thumbnail_diff","cloud_sent":false] }
        guard let (image,sha)=load(r["image"],r["sha256"]) else { return visionError("image_scope_hash_or_size_invalid") }
        if op=="ocr" {
            guard let raw=r["query"] as? String, !raw.isEmpty,raw.count<=96 else { return visionError("invalid_query") }
            let query=raw.precomposedStringWithCanonicalMapping
            let chinese=raw.range(of:"\\p{Han}",options:.regularExpression) != nil
            let request=VNRecognizeTextRequest();request.recognitionLevel = chinese ? .accurate:.fast
            request.usesLanguageCorrection=false;request.usesCPUOnly=true
            request.recognitionLanguages=chinese ? ["zh-Hans","en-US"]:["en-US"]
            let reply=VisionReply()
            // Keep the caller's main run loop available to Vision/OS services;
            // synchronous recognition on the CLI main thread can deadlock.
            DispatchQueue.global(qos:.utility).async {
                do { try VNImageRequestHandler(cgImage:image,options:[:]).perform([request]) }
                catch { reply.publish(visionError("local_OCR_failed"));return }
                var matches:[[String:Any]]=[]
                for row in request.results ?? [] {
                    guard let text=row.topCandidates(1).first,text.confidence>=0.5,text.string.precomposedStringWithCanonicalMapping==query else { continue }
                    let rect=row.boundingBox
                    let box=[rect.minX*Double(image.width),(1-rect.maxY)*Double(image.height),rect.width*Double(image.width),rect.height*Double(image.height)]
                    matches.append(["text":text.string,"confidence":text.confidence,"bounds_pixels":box])
                }
                reply.publish(["status":"ok","matches":matches,"width":image.width,"height":image.height,"sha256":sha,"source":"local_Apple_Vision_top_candidate_only","cloud_sent":false,"actionability":"NOT_PROVEN","recognition_profile":chinese ? "accurate_Chinese_CPU":"fast_Latin_CPU"])
            }
            let deadline=Date(timeIntervalSinceNow:6)
            while reply.read()==nil && Date()<deadline { RunLoop.current.run(until:Date(timeIntervalSinceNow:0.01)) }
            if let result=reply.read() { return result }
            request.cancel();terminateAfterResponse=true
            return visionError("local_OCR_deadline_exceeded")
        }
        if op=="diff" {
            guard let (other,otherSHA)=load(r["other_image"],r["other_sha256"]),image.width==other.width,image.height==other.height else { return visionError("comparison_scope_or_dimensions_invalid") }
            let scale=min(1.0,512.0/Double(max(image.width,image.height)))
            let w=max(1,Int(Double(image.width)*scale));let h=max(1,Int(Double(image.height)*scale))
            func pixels(_ value:CGImage) -> [UInt8]? {
                var result=[UInt8](repeating:0,count:w*h*4)
                let ok=result.withUnsafeMutableBytes { bytes -> Bool in
                    guard let context=CGContext(data:bytes.baseAddress,width:w,height:h,bitsPerComponent:8,bytesPerRow:w*4,space:CGColorSpaceCreateDeviceRGB(),bitmapInfo:CGImageAlphaInfo.premultipliedLast.rawValue|CGBitmapInfo.byteOrder32Big.rawValue) else { return false }
                    context.interpolationQuality = .none;context.draw(value,in:CGRect(x:0,y:0,width:w,height:h));return true
                }
                return ok ? result:nil
            }
            guard let a=pixels(image),let b=pixels(other) else { return visionError("pixel_conversion_failed") }
            var total:UInt64=0;var changed=0
            for index in 0..<(w*h) {
                var largest=0
                for channel in 0..<3 { let delta=abs(Int(a[index*4+channel])-Int(b[index*4+channel]));total += UInt64(delta);largest=max(largest,delta) }
                if largest>12 { changed += 1 }
            }
            return ["status":"ok","raw_bytes_equal":sha==otherSHA,"thumbnail_width":w,"thumbnail_height":h,
                    "thumbnail_changed_fraction":Double(changed)/Double(w*h),"thumbnail_mean_absolute_RGB_difference":Double(total)/Double(w*h*3*255),
                    "method":"bounded_thumbnail_difference_not_semantic_verification","cloud_sent":false,"action_sent":false]
        }
        return visionError("unsupported_vision_operation")
    }
}
let root=CommandLine.arguments.count==2 ? CommandLine.arguments[1] : "/nonexistent-localpilot-capture-root"
let mainPort=Port();RunLoop.main.add(mainPort,forMode:.default)
let vision=WindowVision(root)
while let line=readLine() {
    autoreleasepool {
        guard line.utf8.count<=32768,let request=(try? JSONSerialization.jsonObject(with:Data(line.utf8))) as? [String:Any] else { print(String(data:visionJSON(visionError("invalid_request")),encoding:.utf8)!);fflush(stdout);return }
        print(String(data:visionJSON(vision.execute(request)),encoding:.utf8)!);fflush(stdout)
    }
    if vision.terminateAfterResponse { exit(0) }
}
