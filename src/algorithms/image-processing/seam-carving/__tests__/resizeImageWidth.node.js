import fs from 'fs';
import { PNG } from 'pngjs';

import resizeImageWidth, { matrix } from '../resizeImageWidth';

const testImageBeforePath = './src/algorithms/image-processing/seam-carving/__tests__/test-image-before.png';
const testImageAfterPath = './src/algorithms/image-processing/seam-carving/__tests__/test-image-after.png';

/**
 * Compares two images and finds the number of different pixels.
 *
 * @param {ImageData} imgA - ImageData for the first image.
 * @param {ImageData} imgB - ImageData for the second image.
 * @param {number} threshold - Color difference threshold [0..255]. Smaller - stricter.
 * @returns {number} - Number of different pixels.
 */
function pixelsDiff(imgA, imgB, threshold = 0) {
  if (imgA.width !== imgB.width || imgA.height !== imgB.height) {
    throw new Error('Images must have the same size');
  }

  let differentPixels = 0;
  const numColorParams = 4; // RGBA

  for (let pixelIndex = 0; pixelIndex < imgA.data.length; pixelIndex += numColorParams) {
    // Get pixel's color for each image.
    const [aR, aG, aB] = imgA.data.subarray(pixelIndex, pixelIndex + numColorParams);
    const [bR, bG, bB] = imgB.data.subarray(pixelIndex, pixelIndex + numColorParams);

    // Get average pixel's color for each image (make them greyscale).
    const aAvgColor = Math.floor((aR + aG + aB) / 3);
    const bAvgColor = Math.floor((bR + bG + bB) / 3);

    // Compare pixel colors.
    if (Math.abs(aAvgColor - bAvgColor) > threshold) {
      differentPixels += 1;
    }
  }

  return differentPixels;
}

const pngLoad = (path) => new Promise((resolve) => {
  fs.createReadStream(path)
    .pipe(new PNG())
    .on('parsed', function Parsed() {
      /** @type {ImageData} */
      const imageData = {
        colorSpace: 'srgb',
        width: this.width,
        height: this.height,
        data: this.data,
      };
      resolve(imageData);
    });
});

describe('resizeImageWidth', () => {
  it('should perform content-aware image width reduction', async () => {
    const imgBefore = await pngLoad(testImageBeforePath);
    const imgAfter = await pngLoad(testImageAfterPath);

    const toWidth = Math.floor(imgBefore.width / 2);

    const {
      img: imgResized,
      size: resizedSize,
    } = resizeImageWidth({ img: imgBefore, toWidth });

    expect(imgResized).toBeDefined();
    expect(resizedSize).toBeDefined();

    expect(resizedSize).toEqual({ w: toWidth, h: imgBefore.height });
    expect(imgResized.width).toBe(imgAfter.width);
    expect(imgResized.height).toBe(imgAfter.height);

    const colorThreshold = 50;
    const differentPixels = pixelsDiff(imgResized, imgAfter, colorThreshold);

    // Allow 10% of pixels to be different
    const pixelsThreshold = Math.floor((imgAfter.width * imgAfter.height) / 10);

    expect(differentPixels).toBeLessThanOrEqual(pixelsThreshold);
  });
});

describe('matrix', () => {
  const matrixFixtures = [
    {
      name: 'small rectangular matrix',
      input: { w: 3, h: 2, filler: 5 },
      expected: [
        [5, 5, 5],
        [5, 5, 5],
      ],
    },
    {
      name: '1x1 matrix',
      input: { w: 1, h: 1, filler: 42 },
      expected: [
        [42],
      ],
    },
    {
      name: 'zero-containing matrix',
      input: { w: 2, h: 2, filler: 0 },
      expected: [
        [0, 0],
        [0, 0],
      ],
    },
  ];

  const interveningFixture = {
    name: 'intervening valid input',
    input: { w: 4, h: 1, filler: 99 },
    expected: [
      [99, 99, 99, 99],
    ],
  };

  it('is a deterministic pure function with repeated call and input isolation', () => {
    const evidenceCases = [];

    matrixFixtures.forEach(({ name, input, expected }) => {
      // 1. First run in fresh isolated state
      const run1 = matrix(input.w, input.h, input.filler);
      expect(run1).toEqual(expected);
      evidenceCases.push({
        fixture: name,
        run: 'isolated_run_1',
        input,
        expected,
        actual: JSON.parse(JSON.stringify(run1)),
      });

      // 2. Second run in fresh isolated state
      const run2 = matrix(input.w, input.h, input.filler);
      expect(run2).toEqual(expected);
      expect(run2).not.toBe(run1);
      expect(run2[0]).not.toBe(run1[0]);
      evidenceCases.push({
        fixture: name,
        run: 'isolated_run_2',
        input,
        expected,
        actual: JSON.parse(JSON.stringify(run2)),
      });

      // 3. Intervening run with another valid input
      const interveningRun = matrix(
        interveningFixture.input.w,
        interveningFixture.input.h,
        interveningFixture.input.filler,
      );
      expect(interveningRun).toEqual(interveningFixture.expected);
      evidenceCases.push({
        fixture: name,
        run: 'intervening_valid_input',
        input: interveningFixture.input,
        expected: interveningFixture.expected,
        actual: JSON.parse(JSON.stringify(interveningRun)),
      });

      // 4. Run after another valid input to assert earlier runs do not alter results
      const run3 = matrix(input.w, input.h, input.filler);
      expect(run3).toEqual(expected);
      expect(run3).not.toBe(run1);
      expect(run3).not.toBe(run2);
      expect(run3).not.toBe(interveningRun);
      evidenceCases.push({
        fixture: name,
        run: 'run_after_intervening_input',
        input,
        expected,
        actual: JSON.parse(JSON.stringify(run3)),
      });

      // 5. Assert mutation isolation:
      // Mutating an earlier run does not alter subsequent or prior matrices.
      run1[0][0] = -999999;
      expect(run2).toEqual(expected);
      expect(run3).toEqual(expected);

      // And a new run still produces expected result
      const run4 = matrix(input.w, input.h, input.filler);
      expect(run4).toEqual(expected);
      evidenceCases.push({
        fixture: name,
        run: 'run_after_prior_result_mutation',
        input,
        expected,
        actual: JSON.parse(JSON.stringify(run4)),
      });

      // 6. Assert row isolation: rows are independent arrays
      if (input.h > 1) {
        const rowCheck = matrix(input.w, input.h, input.filler);
        rowCheck[0][0] = 777777;
        expect(rowCheck[1][0]).toEqual(expected[1][0]);
      }
    });

    if (process.env.MATRIX_EVIDENCE_PATH) {
      fs.writeFileSync(
        process.env.MATRIX_EVIDENCE_PATH,
        JSON.stringify(evidenceCases, null, 2),
      );
    }
  });
});
