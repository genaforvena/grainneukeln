def calculate_step(beats):
    # Calculate the step size as the average distance between the beats
    step = 0
    for i in range(1, len(beats)):
        step += beats[i] - beats[i - 1]
    step /= len(beats) - 1
    return step