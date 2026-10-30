"""Create a portable PDF from the verified slide renders, retaining editable PPTX."""
import argparse
from pathlib import Path
from reportlab.pdfgen import canvas


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--images',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    images=sorted(args.images.glob('slide-??.png'))
    if len(images)!=12:raise ValueError('Expected exactly 12 verified slide images')
    target=canvas.Canvas(str(args.output),pagesize=(960,540))
    target.setTitle('localpilot 答辩展示副本')
    target.setAuthor('大肥鱼队')
    for image in images:
        target.drawImage(str(image),0,0,width=960,height=540)
        target.showPage()
    target.save()
    print(str(args.output.resolve()))


if __name__=='__main__':main()
