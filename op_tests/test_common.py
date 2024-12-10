# Copyright (c) 2024 Advanced Micro Devices, Inc.  All rights reserved.
#
# -*- coding:utf-8 -*-
# @Script: test_common.py
# @Author: valarLip
# @Email: lingpeng.jin@amd.com
# @Create At: 2024-11-03 15:53:32
# @Last Modified By: valarLip
# @Last Modified At: 2024-12-10 14:11:39
# @Description: This is description.

import torch
import torch.profiler as tpf
import os
import numpy as np
import pandas as pd
from ater import logger


def perftest(num_iters=100, num_warmup=20):
    def decorator(func):
        def wrapper(*args, **kwargs):
            if int(os.environ.get('ATER_LOG_MORE', 0)):
                latencies = []
                start_event = torch.cuda.Event(enable_timing=True)
                end_event = torch.cuda.Event(enable_timing=True)
                for _ in range(num_iters+num_warmup):
                    start_event.record()
                    data = func(*args, **kwargs)
                    end_event.record()
                    end_event.synchronize()
                    latencies.append(start_event.elapsed_time(end_event))
                avg = np.mean(latencies[num_warmup:]) * 1000
                logger.info(f'avg: {avg} ms/iter from cuda.Event')
            with tpf.profile(activities=[tpf.ProfilerActivity.CPU, tpf.ProfilerActivity.CUDA],
                             profile_memory=True,
                             with_stack=True,
                             with_modules=True,
                             record_shapes=True,
                             #  on_trace_ready=tpf.tensorboard_trace_handler(
                             #      './ater_logs/'),
                             schedule=tpf.schedule(wait=1,
                                                   warmup=num_warmup,
                                                   active=num_iters),) as prof:
                for _ in range(1+num_iters+num_warmup):
                    data = func(*args, **kwargs)
                    prof.step()
            avg = get_trace_perf(prof, num_iters)
            return data, avg
        return wrapper
    return decorator


def get_trace_perf(prof, num_iters):
    df = []
    for el in prof.key_averages():
        if 'ProfilerStep*' not in el.key:
            df.append(vars(el))
    df = pd.DataFrame(df)
    cols = ['key', 'count',
            'cpu_time_total', 'self_cpu_time_total',
            'device_time_total', 'self_device_time_total',
            'self_device_memory_usage',
            'device_type',]
    cols = [el for el in df.columns if el in cols]
    df = df[(df.self_cpu_time_total > 0) | (df.self_device_time_total > 0)]

    timerList = ['self_cpu_time_total', 'self_device_time_total', ]
    df = df[cols].sort_values(timerList, ignore_index=True)
    avg_name = '[avg ms/iter]'
    for el in timerList:
        df.at[avg_name, el] = df[el].sum()/num_iters
    if int(os.environ.get('ATER_LOG_MORE', 0)):
        logger.info(f'{df}')
    return df.at[avg_name, 'self_device_time_total']


def checkAllclose(a, b, rtol=1e-2, atol=1e-2, msg=''):
    isClose = torch.isclose(a, b, rtol=rtol, atol=atol)
    mask = ~isClose
    if isClose.all():
        logger.info(f'{msg}[checkAllclose passed~]')
    else:
        percent = (a[mask]).numel()/a.numel()
        delta = (a-b)[mask]
        if percent > 0.01:
            logger.info(f'''{msg}[checkAllclose failed!]
        a:  {a.shape}
            {a[mask]}
        b:  {b.shape}
            {b[mask]}
    dtlta:
            {delta}''')
        else:
            logger.info(
                f'''{msg}[checkAllclose waring!] a and b results are not all close''')
        logger.info(
            f'-->max delta:{delta.max()}, delta details: {percent:.1%} ({(a[mask]).numel()} of {a.numel()}) elements {atol=} {rtol=}')


def tensor_dump(x: torch.tensor, name: str):
    x_cpu = x.cpu().view(torch.uint8)
    filename = f'{name}.bin'
    x_cpu.numpy().tofile(filename)
    logger.info(f'saving {filename} {x.shape}, {x.dtype}')

    with open(f'{name}.meta', 'w') as f:
        f.writelines([f'{el}\n' for el in [x.shape, x.dtype]])


def tensor_load(filename: str):
    DWs = np.fromfile(filename, dtype=np.uint32)
    metafile = '.'.join(filename.split('.')[:-1])+'.meta'
    shape, dtype = [eval(line.strip()) for line in open(metafile)]
    return torch.tensor(DWs).view(dtype).view(shape)
